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

──────────────────────────────────────────────────────────────────────────────
OFFBOARDING CHECKLIST DİALOQU DEAKTİVASİYADAN DƏRHAL SONRA AÇILIR (Faza 3.4)
──────────────────────────────────────────────────────────────────────────────
`UserManagementUseCase.deactivate_employee()` checklist-i ARTIQ backend
tərəfdə başladır (`offboarding_checklists` portu, bax `composition.py`-dakı
qurulma yeri) — bu kontroller yalnız ONU GÖSTƏRİR: `deactivate_employee()`
uğurla bitdikdən SONRA `session.offboarding_checklists.get_active_for_
employee()` ilə TƏZƏ oxunur (checklist ID `deactivate_employee()`-in
qaytardığı `OffboardingReview`-da YOXDUR, bax use case-in `_start_offboarding_
checklist` şərhi — yalnız `bool | None` daşıyır). `None` qayıdarsa (Root heç
bir OFFBOARDING bəndi yazmayıb) dialoq AÇILMIR, sükutla keçilir.

`[Checklist-i Bağla]` düyməsi `ChecklistNotCompletableError` alanda SÖNDÜRÜLMÜR
— dialoq açıq qalır, `OffboardingChecklistDialog.set_message()` ilə hansı
bağlayıcı bəndlərin çatışmadığı göstərilir (`team-lead`-in AÇIQ göstərişi,
bax həmin dialoqun modul başlığı).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.value_objects.authorization import SystemRole
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.entities.offboarding_checklist import OffboardingChecklistItem
    from src.domain.value_objects.identifiers import EmployeeId, OffboardingChecklistId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import UsersScreen
    from src.presentation.screens.offboarding_checklist import OffboardingChecklistDialog

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
        """İşçini deaktiv edir — AÇIQ qalan bağlantılar ƏVVƏLCƏ göstərilir (HR-4).

        ──────────────────────────────────────────────────────────────────────
        SİYAHI QƏRARDAN ƏVVƏL GƏLİR — SONRA DEYİL
        ──────────────────────────────────────────────────────────────────────
        İşdən çıxma anında ALTI şey açıq qala bilər: bağlanmamış gündaxili
        icazə, təhvil verilməmiş tapşırıq, tutulmuş GƏLƏCƏK növbə, istifadə
        olunmamış illik məzuniyyət, qüvvədə olan sənəd və silinməmiş üz
        şablonu. Heç biri BLOKLAMIR (işdən çıxarma hüquqi faktdır və sistem
        onu «tapşırığın var» deyə dayandıra bilməz), lakin admin bunları
        QƏRARDAN SONRA görsəydi, artıq geri dönüşü olmayan addımı atmış
        olardı — ona görə `preview_offboarding()` təsdiq dialoqundan ƏVVƏL
        oxunur.

        MƏTN EKRANDA QURULMUR: `OffboardingReview.checklist_az()` hazır
        Azərbaycanca sətirləri verir — eyni siyahı audit sətrinə də düşür,
        yəni iki mənbə ayrıla bilməz.

        ÖN-BAXIŞ UĞURSUZ OLARSA DEAKTİVASİYA DAYANMIR: siyahı KÖMƏKÇİ
        məlumatdır və onun oxunmaması hüquqi əməliyyatı bloklamamalıdır
        (use case-in öz «BLOKLAMIR» qərarının davamı).
        """
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            "İşçini deaktiv et",
            f"{full_name} niyə deaktiv edilir? GERİ QAYTARILA BİLMİR — "
            "yenidən işə götürülərsə yeni işçi kartı açılır."
            + self._offboarding_preview(full_name),
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
        self._open_offboarding_checklist(screen, employee_id=employee_id, full_name=full_name)

    def _open_offboarding_checklist(
        self, screen: UsersScreen, *, employee_id: EmployeeId, full_name: str
    ) -> None:
        """Deaktivasiyadan DƏRHAL SONRA checklist-i göstərir (modul başlığı).

        Oxu KÖMƏKÇİDİR: uğursuz olsa (şablon yoxdur, port bağlanmayıb, sorğu
        xətası) dialoq sadəcə AÇILMIR — deaktivasiya ARTIQ commit olunub,
        bunu geri qaytarmaq YANLIŞ olardı.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                checklist = session.offboarding_checklists.get_active_for_employee(
                    actor=self._actor, employee_id=employee_id
                )
        except Exception:
            _error_log.warning("USER_LIFECYCLE_OFFBOARDING_CHECKLIST_READ_FAILED", exc_info=True)
            return
        if checklist is None:
            return

        from src.presentation.screens.offboarding_checklist import (  # noqa: PLC0415
            OffboardingChecklistDialog,
        )

        dialog = OffboardingChecklistDialog(
            screen.theme,
            employee_name=full_name,
            items=[_to_checklist_row(item) for item in checklist.items],
            parent=screen,
        )
        checklist_id = checklist.id
        dialog.item_answered.connect(
            lambda item_id, passed, notes: self._answer_checklist_item(
                dialog, checklist_id=checklist_id, item_id=item_id, passed=passed, notes=notes
            )
        )
        dialog.complete_requested.connect(
            lambda: self._complete_checklist(dialog, checklist_id=checklist_id)
        )
        dialog.exec()

    def _answer_checklist_item(
        self,
        dialog: OffboardingChecklistDialog,
        *,
        checklist_id: OffboardingChecklistId,
        item_id: str,
        passed: bool,
        notes: str,
    ) -> None:
        """Hər Keçdi/Uğursuz seçimi DƏRHAL yazılır (dialoqun modul başlığı)."""
        from uuid import UUID  # noqa: PLC0415

        from src.domain.value_objects.identifiers import (  # noqa: PLC0415
            OffboardingChecklistItemId,
        )

        try:
            parsed_item_id = OffboardingChecklistItemId(UUID(item_id))
        except ValueError:
            dialog.set_message("Bənd identifikatoru düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.offboarding_checklists.answer_item(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    checklist_id=checklist_id,
                    item_id=parsed_item_id,
                    passed=passed,
                    notes=notes or None,
                )
                session.commit()
        except KompasOSError as error:
            dialog.set_message(error.user_message)
        except Exception:
            _error_log.exception("USER_LIFECYCLE_OFFBOARDING_ITEM_ANSWER_FAILED")
            dialog.set_message("Cavab yazılmadı. Yenidən cəhd edin.")

    def _complete_checklist(
        self, dialog: OffboardingChecklistDialog, *, checklist_id: OffboardingChecklistId
    ) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.offboarding_checklists.complete(
                    tenant_id=session.tenant_id, actor=self._actor, checklist_id=checklist_id
                )
                session.commit()
        except KompasOSError as error:
            # `ChecklistNotCompletableError` BURAYA düşür — düymə SÜKUTLA
            # söndürülmür (modul başlığı), dialoq AÇIQ qalır, HR AÇIQ mesaj
            # görür (`error.user_message`, bax `entities/offboarding_
            # checklist.py::ChecklistNotCompletableError`).
            dialog.set_message(error.user_message)
            return
        except Exception:
            _error_log.exception("USER_LIFECYCLE_OFFBOARDING_COMPLETE_FAILED")
            dialog.set_message("Checklist bağlanmadı. Yenidən cəhd edin.")
            return

        dialog.accept()

    def _offboarding_preview(self, full_name: str) -> str:
        """Təsdiq dialoquna əlavə olunan «açıq qalanlar» mətni (HR-4).

        Heç nə açıq deyilsə BOŞ sətir qaytarılır — «hər şey təmizdir» cümləsi
        yazılmır: admin onu oxumağa öyrəşsəydi, siyahı DOLU olduğu gün də
        eyni sürətlə keçib gedərdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    return ""
                review = session.users.preview_offboarding(
                    actor=self._actor,
                    employee_id=employee_id,
                )
        except Exception:
            # Geniş tutma: ön-baxış köməkçidir, hüquqi əməliyyatı dayandırmır.
            _error_log.warning("USER_LIFECYCLE_OFFBOARDING_PREVIEW_FAILED", exc_info=True)
            return ""

        lines = review.checklist_az()
        if not lines:
            return ""
        return "\n\nAÇIQ QALANLAR (bloklamır, məlumat üçün):\n" + "\n".join(
            f"• {line}" for line in lines
        )

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


def _to_checklist_row(item: OffboardingChecklistItem) -> dict[str, str]:
    """`OffboardingChecklistItem` → dialoqun FAKTİKİ gözlədiyi açarlar.

    Açarlar `screens/offboarding_checklist.py::OffboardingChecklistDialog`-un
    `items` docstring-i ilə EYNİDİR (CLAUDE.md §6). Bu ekranın maket yolu
    YOXDUR (`preview_screens.py`) — checklist YALNIZ canlı deaktivasiya
    axınının nəticəsidir, `AnnualLeaveRequestDialog`/`TransferRequestDialog`-
    dan FƏRQLİ olaraq önizləmədə müstəqil açıla bilməz.
    """
    return {
        "id": str(item.id),
        "position_no": str(item.position_no),
        "category": item.category.value,
        "item_text": item.item_text,
        "is_blocking": "1" if item.is_blocking else "0",
        "passed": "" if item.passed is None else ("1" if item.passed else "0"),
        "notes": item.notes or "",
    }


__all__ = [
    "CHANGE_ROLE_ACTION_KEY",
    "DEACTIVATE_ACTION_KEY",
    "RESET_PASSWORD_ACTION_KEY",
    "RESET_PIN_ACTION_KEY",
    "UserLifecycleController",
]
