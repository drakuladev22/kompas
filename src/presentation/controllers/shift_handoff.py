"""Növbə təhvili qeydinin YAZI yolu — `v2backlog.md` Faza 5.3.

`controllers/transfer_requests.py` İLƏ EYNİ NAXIŞ (bax həmin faylın başlığı):

    * Ekran HƏM oxuyur, HƏM yazır — qeyd qoyulduqdan və ya qəbul edildikdən
      SONRA siyahı DƏRHAL yenilənməlidir, yəni `screen_data.py`-ın tək
      `populate()` çağırışı KİFAYƏT ETMİR.
    * Sessiya SAXLANILMIR: hər əməliyyat üçün yenisi açılır və commit edilir.
    * Kioskda İSTİSNA EKRANA ÇIXMIR — kiosk PC-si PAYLAŞILAN cihazdır, modal
      xəta bütün mağazanı bloklayardı. Hər nəticə `set_handoff_message(...)`
      mətninə çevrilir və mətn HƏMİŞƏ `error.user_message`-dən gəlir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ DİALOQ, SƏTİRDAXİLİ SAHƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Kartda daimi mətn sahəsi saxlansaydı, kiosk ekranında (PAYLAŞILAN cihaz) bir
işçinin yarımçıq yazdığı qeyd növbətinin ekranında qalardı — və o, sükutla
başqasının adından göndərilə bilərdi. Dialoq isə bağlananda məzmunu ilə
birlikdə ölür.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from src.domain.value_objects.identifiers import ShiftHandoffNoteId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.entities.shift_handoff import ShiftHandoffNote
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

NOTE_CONFIRMATION = "Təhvil qeydiniz növbəti işçiyə göstəriləcək."
ACKNOWLEDGE_CONFIRMATION = "Təhvili qəbul etdiniz."

_READ_FAILED = "Təhvil qeydləri yüklənmədi."
_NOTE_FAILED = "Təhvil qeydi yazılmadı. Yenidən cəhd edin."
_ACK_FAILED = "Təhvil qəbul edilmədi. Yenidən cəhd edin."


class ShiftHandoffController:
    """İşçi Ana Ekranının "Növbə Təhvili" kartı."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: EmployeeHomeScreen) -> None:
        screen.handoff_note_requested.connect(lambda: self._on_leave_note(screen))
        screen.handoff_acknowledge_requested.connect(
            lambda note_id: self._on_acknowledge(screen, note_id)
        )
        self.refresh(screen)

    def refresh(self, screen: EmployeeHomeScreen, *, message: str = "") -> None:
        """Gözləyən qeydləri yenidən oxuyur — səlahiyyət TƏLƏB ETMİR.

        Görünmə pəncərəsi və «öz qeydim deyil» süzgəci USE CASE-dədir
        (`pending_for_employee`), burada TƏKRARLANMIR — əks halda eyni qayda
        iki yerdə yaşayardı və biri dəyişəndə digəri sükutla köhnələrdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                notes = session.shift_handoffs.pending_for_employee(
                    tenant_id=session.tenant_id, employee=self._actor
                )
                rows = [_to_row(session, note) for note in notes]
        except KompasOSError as error:
            screen.set_handoff_notes([])
            screen.set_handoff_message(error.user_message)
            return
        except Exception:
            _error_log.exception("SHIFT_HANDOFF_READ_FAILED")
            screen.set_handoff_notes([])
            screen.set_handoff_message(_READ_FAILED)
            return

        screen.set_handoff_notes(rows)
        screen.set_handoff_message(message)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_leave_note(self, screen: EmployeeHomeScreen) -> None:
        """`[Təhvil Qeydi Yaz]` — dialoq açılır, mətn use case-ə gedir."""
        from src.presentation.screens.shift_handoff import (  # noqa: PLC0415
            ShiftHandoffNoteDialog,
        )

        dialog = ShiftHandoffNoteDialog(screen.theme, parent=screen)
        dialog.submitted.connect(lambda note: self._submit(screen, note))
        dialog.exec()

    def _submit(self, screen: EmployeeHomeScreen, note: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.shift_handoffs.leave_note(
                    tenant_id=session.tenant_id, employee=self._actor, note=note
                )
                session.commit()
        except KompasOSError as error:
            # Uzunluq həddi (Root parametri), filialı olmayan işçi və s.
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("SHIFT_HANDOFF_NOTE_FAILED")
            self.refresh(screen, message=_NOTE_FAILED)
            return

        self.refresh(screen, message=NOTE_CONFIRMATION)

    def _on_acknowledge(self, screen: EmployeeHomeScreen, note_id_text: str) -> None:
        """`[Qəbul edirəm]` — KONKRET qeydə yazılır (toplu qəbul YOXDUR)."""
        try:
            note_id = ShiftHandoffNoteId(uuid.UUID(note_id_text))
        except ValueError:
            self.refresh(screen, message="Qeyd identifikatoru düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.shift_handoffs.acknowledge(
                    tenant_id=session.tenant_id, employee=self._actor, note_id=note_id
                )
                session.commit()
        except KompasOSError as error:
            # «Öz qeydimi qəbul edə bilmərəm», «artıq qəbul edilib» bura düşür.
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("SHIFT_HANDOFF_ACK_FAILED")
            self.refresh(screen, message=_ACK_FAILED)
            return

        self.refresh(screen, message=ACKNOWLEDGE_CONFIRMATION)


def _to_row(session: Session, note: ShiftHandoffNote) -> dict[str, str]:
    """Aqreqatı ekran sətrinə çevirir — açarlar maket yolu ilə EYNİDİR.

    MÜƏLLİFİN ADI BİR SORĞU İLƏ OXUNUR (`employees.get`) və tapılmazsa BOŞ
    qalır: deaktiv edilmiş işçinin qeydi GÖSTƏRİLMƏLİDİR — kassa vəziyyəti
    haqqında məlumat müəllifin statusundan asılı deyil.
    """
    author = session.uow.employees.get(note.author_employee_id)
    return {
        "id": str(note.id),
        "note": note.note,
        "author": author.full_name if author is not None else "",
        # SAAT:DƏQİQƏ kifayətdir — qeyd görünmə pəncərəsi içindədir (ən çoxu
        # bir neçə saat), tam tarix ekranda yer tutub heç nə əlavə etməzdi.
        "time": note.created_at.astimezone().strftime("%H:%M"),
    }
