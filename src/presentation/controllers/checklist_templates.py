"""Checklist bənd şablonlarının YAZI yolu — `v2backlog.md` Faza 3.4 + 4.1.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screen_data.py`-DA DEYİL
──────────────────────────────────────────────────────────────────────────────
`catalog_admin.py` (`CatalogScreen`) ilə EYNİ əsaslandırma: bu ekran HƏM
oxuyur, HƏM yazır (yeni bənd, redaktə, deaktiv/aktiv) və hər yazıdan sonra
siyahını yenidən oxumalıdır — bu dövrə `populate()`-ın tək çağırışından uzun
yaşayır (CLAUDE.md §6).

──────────────────────────────────────────────────────────────────────────────
"DEAKTİV ET" SİLMƏ DEYİL — `catalog_admin.py` İLƏ EYNİ NAXIŞ
──────────────────────────────────────────────────────────────────────────────
`toggle_requested` İKİ istiqamətlidir: aktiv sətir üçün
`ChecklistItemTemplateUseCase.deactivate()`, deaktiv sətir üçün `save()`
(`is_active=True`, `deactivated_at=None` ilə yenidən yazılır) — AYRI
"reactivate" metodu YOXDUR, repository `ON CONFLICT (id)` ilə UPSERT edir.

──────────────────────────────────────────────────────────────────────────────
SIRA NÖMRƏSİ AVTOMATİK TƏKLİF OLUNUR
──────────────────────────────────────────────────────────────────────────────
Yeni bənd yaradarkən dialoq "sonuncu + 1" ilə açılır (`_next_position_no`) —
admin BOŞ sıra ilə başlamır, LAKİN dəyəri istəsə dəyişə bilər (redaktə
zamanı sıralamanı dəyişmək lazım ola bilər). Repository `position_no`
unikallığını `(tenant_id, owner_type, owner_key, position_no)` üzərindən
tələb ETMİR (bax `hr_lifecycle_v2_repositories.py::save`, sadə UPSERT) —
təkrarlanan sıra domen qaydası DEYİL, YALNIZ görünüş qarışıqlığı yaradar,
ona görə burada da yoxlanmır (`CatalogEntryDialog` ilə eyni minimal-yoxlama
fəlsəfəsi).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.catalogs import ChecklistItemTemplate
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.checklist_templates import ChecklistTemplateScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

_SAVE_FAILED_TITLE = "Bənd yadda saxlanmadı"
_TOGGLE_FAILED_TITLE = "Vəziyyət dəyişmədi"
_LIST_FAILED_TITLE = "Şablonlar oxunmadı"


class ChecklistTemplateController:
    """`ChecklistTemplateScreen`-i `ChecklistItemTemplateUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: `screens/checklist_templates.py::OFFBOARDING_OWNER_KEY` ilə EYNİ
        #: sentinel — presentasiya qatı domen sabitini idxal etmir (CLAUDE.md
        #: §3), buna görə mətn burada da TƏKRAR yazılır.
        self._owner_key = "OFFBOARDING"
        self._templates: list[ChecklistItemTemplate] = []

    def attach(self, screen: ChecklistTemplateScreen) -> None:
        screen.owner_type_changed.connect(
            lambda owner_type: self._on_owner_type(screen, owner_type)
        )
        screen.owner_key_lookup_requested.connect(
            lambda owner_key: self._on_owner_key_lookup(screen, owner_key)
        )
        screen.create_requested.connect(lambda: self._open_create(screen))
        screen.edit_requested.connect(lambda template_id: self._open_edit(screen, template_id))
        screen.toggle_requested.connect(lambda template_id: self._toggle(screen, template_id))
        self.refresh(screen)

    # ------------------------------ süzgəc ------------------------------------ #

    def _on_owner_type(self, screen: ChecklistTemplateScreen, owner_type: str) -> None:
        from src.presentation.screens.checklist_templates import (  # noqa: PLC0415
            OWNER_TYPE_OFFBOARDING,
        )

        if owner_type == OWNER_TYPE_OFFBOARDING:
            self._owner_key = "OFFBOARDING"
            self.refresh(screen)
        else:
            # FIELD_REPORT — axtarış gözlənilir (ekran ARTIQ boş-vəziyyət
            # göstərir, bax `ChecklistTemplateScreen._set_owner_type`).
            self._owner_key = ""
            self._templates = []

    def _on_owner_key_lookup(self, screen: ChecklistTemplateScreen, owner_key: str) -> None:
        if not owner_key:
            return
        self._owner_key = owner_key
        self.refresh(screen)

    # -------------------------------- oxuma ------------------------------------ #

    def refresh(self, screen: ChecklistTemplateScreen) -> None:
        if not self._owner_key:
            # FIELD_REPORT-da hələ heç bir açar axtarılmayıb — ekran ARTIQ
            # "açarı daxil edin" boş-vəziyyətindədir, sorğu göndərmirik.
            return

        from src.domain.value_objects.catalogs import ChecklistOwnerType  # noqa: PLC0415

        try:
            with self._context.session(user_id=self._actor.id) as session:
                self._templates = session.checklist_templates.list_for_management(
                    session.tenant_id,
                    self._actor,
                    owner_type=ChecklistOwnerType(screen.owner_type),
                    owner_key=self._owner_key,
                )
        except KompasOSError as error:
            screen.set_entries([])
            screen.show_error(title=_LIST_FAILED_TITLE, message=error.user_message)
            return
        except Exception:
            _error_log.exception("CHECKLIST_TEMPLATE_LIST_FAILED")
            screen.set_entries([])
            screen.show_error(
                title=_LIST_FAILED_TITLE, message="Siyahı oxuna bilmədi. Yenidən cəhd edin."
            )
            return

        screen.set_entries([_to_row(template) for template in self._templates])

    # -------------------------------- yazı ------------------------------------ #

    def _next_position_no(self) -> int:
        if not self._templates:
            return 1
        return max(template.position_no for template in self._templates) + 1

    def _open_create(self, screen: ChecklistTemplateScreen) -> None:
        from src.presentation.screens.checklist_templates import (  # noqa: PLC0415
            OWNER_TYPE_FIELD_REPORT,
            ChecklistTemplateDialog,
        )

        owner_type = screen.owner_type
        if owner_type == OWNER_TYPE_FIELD_REPORT and not self._owner_key:
            screen.show_error(
                title=_SAVE_FAILED_TITLE, message="Əvvəlcə kataloq açarını axtarıb göstərin."
            )
            return

        dialog = ChecklistTemplateDialog(
            screen.theme,
            owner_type=owner_type,
            title="Yeni Bənd",
            owner_key=self._owner_key,
            position_no=str(self._next_position_no()),
            parent=screen,
        )
        dialog.submitted.connect(
            lambda owner_key, position_no, item_text, is_blocking, photo_required, category: (
                self._save(
                    screen,
                    template_id=None,
                    owner_type=owner_type,
                    owner_key=owner_key,
                    position_no=position_no,
                    item_text=item_text,
                    is_blocking=is_blocking,
                    photo_required=photo_required,
                    category=category,
                )
            )
        )
        dialog.exec()

    def _open_edit(self, screen: ChecklistTemplateScreen, template_id: str) -> None:
        from src.presentation.screens.checklist_templates import (  # noqa: PLC0415
            ChecklistTemplateDialog,
        )

        template = self._find(template_id)
        if template is None:
            screen.show_error(
                title=_SAVE_FAILED_TITLE, message="Bu bənd artıq siyahıda deyil. Yeniləyin."
            )
            return

        dialog = ChecklistTemplateDialog(
            screen.theme,
            owner_type=template.owner_type.value,
            title="Bəndi Redaktə Et",
            owner_key=template.owner_key,
            position_no=str(template.position_no),
            item_text=template.item_text,
            is_blocking=template.is_blocking,
            photo_required=template.photo_required,
            category=template.category.value if template.category is not None else "",
            parent=screen,
        )
        dialog.submitted.connect(
            lambda owner_key, position_no, item_text, is_blocking, photo_required, category: (
                self._save(
                    screen,
                    template_id=template.template_id,
                    owner_type=template.owner_type.value,
                    owner_key=owner_key,
                    position_no=position_no,
                    item_text=item_text,
                    is_blocking=is_blocking,
                    photo_required=photo_required,
                    category=category,
                )
            )
        )
        dialog.exec()

    def _save(
        self,
        screen: ChecklistTemplateScreen,
        *,
        template_id: object,
        owner_type: str,
        owner_key: str,
        position_no: str,
        item_text: str,
        is_blocking: bool,
        photo_required: bool,
        category: str,
    ) -> None:
        from src.domain.value_objects.catalogs import (  # noqa: PLC0415
            ChecklistItemCategory,
            ChecklistItemTemplate,
            ChecklistOwnerType,
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                entry = ChecklistItemTemplate(
                    template_id=template_id,  # type: ignore[arg-type]
                    tenant_id=session.tenant_id,
                    owner_type=ChecklistOwnerType(owner_type),
                    owner_key=owner_key,
                    position_no=int(position_no),
                    item_text=item_text,
                    is_blocking=is_blocking,
                    photo_required=photo_required,
                    category=ChecklistItemCategory(category) if category else None,
                )
                session.checklist_templates.save(session.tenant_id, self._actor, entry)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title=_SAVE_FAILED_TITLE, message=error.user_message)
            return
        except Exception:
            _error_log.exception("CHECKLIST_TEMPLATE_SAVE_FAILED")
            screen.show_error(
                title=_SAVE_FAILED_TITLE, message="Dəyişiklik saxlanmadı. Yenidən cəhd edin."
            )
            return

        self.refresh(screen)

    def _toggle(self, screen: ChecklistTemplateScreen, template_id: str) -> None:
        from src.domain.value_objects.identifiers import (  # noqa: PLC0415
            ChecklistItemTemplateId,
        )

        template = self._find(template_id)
        if template is None:
            screen.show_error(
                title=_TOGGLE_FAILED_TITLE, message="Bu bənd artıq siyahıda deyil. Yeniləyin."
            )
            return

        try:
            parsed_id = ChecklistItemTemplateId(uuid.UUID(template_id))
        except ValueError:
            screen.show_error(
                title=_TOGGLE_FAILED_TITLE, message="Bənd identifikatoru düzgün deyil."
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                if template.is_active:
                    session.checklist_templates.deactivate(
                        session.tenant_id, self._actor, parsed_id
                    )
                else:
                    # `deactivate()`-in əksi metod YOXDUR (modul başlığı) —
                    # `save()` `is_active=True`/`deactivated_at=None` ilə
                    # yenidən yazır.
                    reactivated = replace(template, is_active=True, deactivated_at=None)
                    session.checklist_templates.save(session.tenant_id, self._actor, reactivated)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title=_TOGGLE_FAILED_TITLE, message=error.user_message)
            return
        except Exception:
            _error_log.exception("CHECKLIST_TEMPLATE_TOGGLE_FAILED")
            screen.show_error(
                title=_TOGGLE_FAILED_TITLE, message="Dəyişiklik saxlanmadı. Yenidən cəhd edin."
            )
            return

        self.refresh(screen)

    # ------------------------------ köməkçi ------------------------------------ #

    def _find(self, template_id: str) -> ChecklistItemTemplate | None:
        for template in self._templates:
            if str(template.template_id) == template_id:
                return template
        return None


def _to_row(template: ChecklistItemTemplate) -> dict[str, str]:
    """`ChecklistItemTemplate` → `ChecklistTemplateScreen.set_entries`-in gözlədiyi açarlar."""
    return {
        "id": str(template.template_id),
        "position_no": str(template.position_no),
        "category": template.category.value if template.category is not None else "",
        "item_text": template.item_text,
        "is_blocking": "1" if template.is_blocking else "0",
        "photo_required": "1" if template.photo_required else "0",
        "is_active": "1" if template.is_active else "0",
    }


__all__ = ["ChecklistTemplateController"]
