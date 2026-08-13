"""#17 İşçi Sənədlərinin yazı yolu — `UsersScreen`-in "···" menyusu (Faza 7).

`controllers/pos_threshold.py` ilə EYNİ naxış: heç bir qapı burada TƏKRARLANMIR
— `EmployeeDocumentUseCase` daxilindədir (`can_manage_employee_documents`
yoxlaması, audit). Kontrollerin yeganə əlavəsi istisnanın İSTİFADƏÇİYƏ İZAH
EDİLMƏSİDİR (`permission_matrix.py`-dəki eyni qərar) və Qt-spesifik giriş
(fayl seçimi, tarix mətninin parçalanması, "Deaktiv Et" səbəbinin soruşulması).

Sessiya SAXLANMIR (CLAUDE.md §6): hər əməliyyat üçün yeni sessiya açılır və
commit edilir; uğurlu yazıdan sonra dialoqun cədvəli TƏZƏ sorğu ilə doldurulur
(`_refresh_dialog`) — bağlanıb-açılmır, çünki admin eyni pəncərədə bir neçə
sənəd ardıcıl əlavə edə bilməlidir.

──────────────────────────────────────────────────────────────────────────────
FAYL YÜKLƏMƏSİ — MÖVCUD SÜBUT NÖVBƏSİNİN TƏKRAR İSTİFADƏSİ (#17, Faza 7)
──────────────────────────────────────────────────────────────────────────────
Yeni saxlama qatı QURULMUR: `EvidenceUploadQueue` artıq `owner_type`/`owner_id`
ilə ÜMUMİLƏŞDİRİLİB (bax `upload_queue.py` başlığı) — bu kontroller ona
`owner_type=EMPLOYEE_DOCUMENT` ilə yazır, `fine_entry.py`-dəki "əvvəlcə diskə,
sonra bazaya" sırasının EYNİ PATTERN-i işləyir (`_enqueue_file`).

FƏRQ (fine_entry.py-dan): burada sübut sənəd üçün HÜQUQİ MƏCBURİ DEYİL —
`file_ref` NULL qala bilər (`EmployeeDocument.file_ref` DB qaydası). Ona görə
sıra TƏRSDİR: ƏVVƏLCƏ sənəd sətri yaranır (`create_document`, `document.id`
alınır), SONRA fayl (varsa) həmin ID ilə növbəyə düşür. Fayl seçilməyibsə
`_enqueue_file` heç çağırılmır və sənəd YENƏ DƏ yaranır — "A variantı"nın
məqsədi məhz budur: yazı yolu heç vaxt fayl seçiminə GİROV qalmır.

`EmployeeDocumentUseCase.attach_file()` BURADA BİLAVASİTƏ ÇAĞIRILMIR — o,
yükləmə TAMAMLANANDA (`composition.py: _attach_evidence` →
`attach_uploaded_file`) arxa planda işə düşür, çünki Drive-a yazı bir neçə
saniyə/dəqiqə çəkə bilər və kontroller ekranı bloklaya bilməz.

──────────────────────────────────────────────────────────────────────────────
NİYƏ İŞÇİ ADI İLƏ AXTARIŞ (`pos_threshold.py` İLƏ EYNİ MƏHDUDİYYƏT)
──────────────────────────────────────────────────────────────────────────────
`UsersScreen.action_requested` domen ID-si deyil, GÖRÜNƏN adı ötürür.
`_find_employee_id` `controllers/pos_threshold.py`-dakı EYNİ funksiyanın
təkrarıdır — iki kontroller arasında import bağı qurmaq əvəzinə hər kontroller
öz nüsxəsini saxlayır (mövcud `_employee_names`/`_find_employee_id`
təkrarlarının davamı, bax `pos_threshold.py` başlığı).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.entities.employee_document import EmployeeDocument
    from src.domain.value_objects.identifiers import EmployeeDocumentId, EmployeeId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import EmployeeDocumentDialog, UsersScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `UsersScreen.ACTIONS`-dəki açar — YALNIZ bu emal olunur.
EMPLOYEE_DOCUMENT_ACTION_KEY = "employee_documents"


class UsersEmployeeDocumentController:
    """`UsersScreen`-in "Sənədlər" bəndini `EmployeeDocumentUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: UsersScreen) -> None:
        screen.action_requested.connect(lambda key, name: self._on_action(screen, key, name))

    def _on_action(self, screen: UsersScreen, key: str, full_name: str) -> None:
        if key != EMPLOYEE_DOCUMENT_ACTION_KEY:
            return
        self._open_dialog(screen, full_name)

    # -------------------------------- açılış ---------------------------------- #

    def _open_dialog(self, screen: UsersScreen, full_name: str) -> None:
        employee_id, rows = self._load(screen, full_name)
        if employee_id is None:
            return

        from src.presentation.screens.group_c import EmployeeDocumentDialog  # noqa: PLC0415

        dialog = EmployeeDocumentDialog(
            screen.theme, employee_name=full_name, documents=rows, parent=screen
        )
        dialog.document_added.connect(
            lambda doc_type, doc_number, expiry_text, blocking, file_path: self._add(
                screen,
                dialog,
                employee_id=employee_id,
                full_name=full_name,
                doc_type=doc_type,
                doc_number=doc_number,
                expiry_text=expiry_text,
                blocking=blocking,
                file_path=file_path,
            )
        )
        dialog.deactivate_requested.connect(
            lambda document_id_text: self._deactivate(
                screen,
                dialog,
                full_name=full_name,
                document_id_text=document_id_text,
            )
        )
        dialog.exec()

    def _load(
        self, screen: UsersScreen, full_name: str
    ) -> tuple[EmployeeId | None, list[dict[str, str]]]:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee_id = _find_employee_id(session, full_name)
                if employee_id is None:
                    screen.show_error(
                        title="İşçi tapılmadı",
                        message="Bu işçi artıq siyahıda deyil. Səhifəni yeniləyin.",
                    )
                    return None, []
                documents = session.employee_documents.list_for_employee(
                    tenant_id=session.tenant_id, actor=self._actor, employee_id=employee_id
                )
                rows = [_to_row(document) for document in documents]
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Sənədlər açıla bilmədi", message=error.user_message)
            return None, []
        except Exception:
            _error_log.exception("EMPLOYEE_DOCUMENTS_LOAD_FAILED")
            screen.show_error(
                title="Sənədlər açıla bilmədi",
                message="Məlumat yüklənmədi. Yenidən cəhd edin.",
            )
            return None, []
        return employee_id, rows

    # -------------------------------- yazı yolu -------------------------------- #

    def _add(
        self,
        screen: UsersScreen,
        dialog: EmployeeDocumentDialog,
        *,
        employee_id: EmployeeId,
        full_name: str,
        doc_type: str,
        doc_number: str,
        expiry_text: str,
        blocking: bool,
        file_path: str,
    ) -> None:
        expiry_date: date | None = None
        if expiry_text:
            try:
                expiry_date = date.fromisoformat(expiry_text)
            except ValueError:
                screen.show_error(
                    title="Tarix yanlışdır",
                    message="Bitmə tarixini YYYY-AA-GG formatında yazın (məs. 2026-12-31).",
                )
                return

        from src.application.use_cases.employee_documents import (  # noqa: PLC0415
            EmployeeDocumentDraft,
        )

        document_id: EmployeeDocumentId | None = None
        store_id: Any = None
        try:
            with self._context.session(user_id=self._actor.id) as session:
                document = session.employee_documents.create_document(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee_id,
                    draft=EmployeeDocumentDraft(
                        doc_type=doc_type,
                        doc_number=doc_number or None,
                        expiry_date=expiry_date,
                        is_blocking=blocking,
                    ),
                )
                document_id = document.id
                # `store_id` fayl növbəsinin Drive qovluq strukturu (`KompasOS/
                # {Mağaza}/{İl-Ay}`) üçün lazımdır — EYNİ sessiyada, ƏLAVƏ
                # sorğu ilə oxunur (bax `_employee_store_id`).
                store_id = _employee_store_id(session, employee_id)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Sənəd əlavə edilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception(
                "EMPLOYEE_DOCUMENT_CREATE_FAILED", extra={"employee_id": str(employee_id)}
            )
            screen.show_error(
                title="Sənəd əlavə edilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        # Sənəd qeydi ARTIQ YARADILIB — fayl SEÇİLMƏYİBSƏ (və ya növbəyə
        # yerləşdirilə bilmirsə) belə, bu, yazı yolunu POZMUR (modul başlığı:
        # "A variantı"nın məqsədi məhz budur).
        if file_path:
            self._enqueue_file(
                screen, document_id=document_id, store_id=store_id, file_path=file_path
            )

        dialog.clear_form()
        self._refresh_dialog(screen, dialog, full_name)

    def _enqueue_file(
        self,
        screen: UsersScreen,
        *,
        document_id: EmployeeDocumentId | None,
        store_id: Any,
        file_path: str,
    ) -> None:
        """Seçilmiş skanı sübut növbəsinə yazır (`owner_type=EMPLOYEE_DOCUMENT`).

        Uğursuzluq burada SƏNƏD QEYDİNİ GERİ QAYTARMIR — sətir ARTIQ yaranıb
        (bax `_add`), ona görə hər xəta mesajı "sənəd qeydi YARADILDI" ilə
        bitir: admin faylı sonradan `attach_file` yolu ilə əlavə edə bilər.
        """
        if document_id is None:  # pragma: no cover - müdafiə xətti, `_add`-də təmin olunur
            return
        if store_id is None:
            screen.show_error(
                title="Fayl yüklənmədi",
                message=(
                    "Bu işçiyə mağaza təyin edilməyib, ona görə fayl növbəyə "
                    "yerləşdirilə bilmədi. Sənəd qeydi YARADILDI."
                ),
            )
            return

        from datetime import UTC, datetime  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from src.infrastructure.storage.upload_queue import UploadOwnerType  # noqa: PLC0415

        path = Path(file_path)
        try:
            content = path.read_bytes()
        except OSError:
            screen.show_error(
                title="Fayl oxunmadı",
                message="Seçilmiş fayl açıla bilmədi. Sənəd qeydi YARADILDI.",
            )
            return

        try:
            # Spool DİSKƏ yazılır, Drive əlçatmaz olsa belə fayl İTMİR — `fine_
            # entry.py`-dəki EYNİ növbə infrastrukturu (bax modul başlığı).
            self._context.evidence_queue().enqueue(
                tenant_id=str(self._context.tenant_id),
                owner_type=UploadOwnerType.EMPLOYEE_DOCUMENT,
                owner_id=str(document_id),
                store_id=store_id,
                filename=path.name,
                content=content,
                taken_at=datetime.now(UTC),
            )
        except KompasOSError as error:
            screen.show_error(title="Fayl yüklənmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception(
                "EMPLOYEE_DOCUMENT_FILE_ENQUEUE_FAILED", extra={"document_id": str(document_id)}
            )
            screen.show_error(
                title="Fayl yüklənmədi",
                message="Fayl növbəyə yerləşdirilmədi. Sənəd qeydi YARADILDI.",
            )
            return

        # Yükləməni DƏRHAL bir dəfə sınayırıq (`fine_entry.py`-dəki EYNİ
        # qərar) — uğursuzluq əhəmiyyətsizdir, element növbədə qalır.
        self._context.run_evidence_uploads()

    def _deactivate(
        self,
        screen: UsersScreen,
        dialog: EmployeeDocumentDialog,
        *,
        full_name: str,
        document_id_text: str,
    ) -> None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        reason, accepted = QInputDialog.getMultiLineText(
            screen,
            "Sənədi deaktiv et",
            "Bu sənəd niyə söndürülür? (sətir SİLİNMİR, yalnız deaktiv edilir)",
        )
        cleaned = reason.strip()
        if not accepted or not cleaned:
            return

        from src.domain.value_objects.identifiers import EmployeeDocumentId  # noqa: PLC0415

        try:
            document_id = EmployeeDocumentId(UUID(document_id_text))
        except ValueError:
            _error_log.error(
                "EMPLOYEE_DOCUMENT_ID_MALFORMED", extra={"document_id": document_id_text}
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.employee_documents.deactivate_document(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    document_id=document_id,
                    reason=cleaned,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Sənəd deaktiv edilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception(
                "EMPLOYEE_DOCUMENT_DEACTIVATE_FAILED", extra={"document_id": document_id_text}
            )
            screen.show_error(
                title="Sənəd deaktiv edilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self._refresh_dialog(screen, dialog, full_name)

    def _refresh_dialog(
        self, screen: UsersScreen, dialog: EmployeeDocumentDialog, full_name: str
    ) -> None:
        """Dialoqu BAĞLAMADAN cədvəli təzələyir — admin ardıcıl sənəd əlavə edə bilsin."""
        _, rows = self._load(screen, full_name)
        dialog.set_documents(rows)


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


def _employee_store_id(session: Session, employee_id: EmployeeId) -> Any:
    """Fayl növbəsinin Drive qovluq strukturu üçün lazımdır (bax `_enqueue_file`).

    `None` qaytarır — işçiyə mağaza TƏYİN EDİLMƏYİBSƏ (`employees.store_id`
    `ON DELETE SET NULL`, sxem 354-cü sətir). Bu, xəta DEYİL: sənəd qeydi hər
    halda yaranır, YALNIZ fayl yükləməsi bloklanır (`_enqueue_file` bunu
    ekranda izah edir).
    """
    employee = session.uow.employees.get(employee_id)
    return employee.store_id if employee is not None else None


def _to_row(document: EmployeeDocument) -> dict[str, str]:
    """`EmployeeDocument` → `EmployeeDocumentDialog.set_documents()`-in gözlədiyi sətir."""
    # `date.today()` — YALNIZ ekran çipi üçün (təqvim GÜNÜ, an deyil).
    # Həqiqi bloklama xəbərdarlığı `DocumentComplianceAdvisor`-dadır və
    # `Clock` portu ilə determinstik işləyir (`open_shift.py`-dəki eyni qərar).
    today = date.today()  # noqa: DTZ011
    if not document.is_active:
        status = "Deaktiv"
    elif document.is_blocking and document.is_expired_on(today):
        status = "Bitib"
    else:
        status = "Aktiv"
    return {
        "id": str(document.id),
        "doc_type": document.doc_type,
        "doc_number": document.doc_number or "",
        "expiry_date": document.expiry_date.isoformat() if document.expiry_date else "",
        "is_blocking": "true" if document.is_blocking else "false",
        "status": status,
    }


__all__ = ["EMPLOYEE_DOCUMENT_ACTION_KEY", "UsersEmployeeDocumentController"]
