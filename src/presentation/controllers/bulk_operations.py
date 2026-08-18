"""Toplu Əməliyyatlar (#29, kompas1.md Faza 5) — CSV idxalı + mağaza şablonunun YAZI yolu.

CLAUDE.md §6: sessiya SAXLANMIR — hər əməliyyat üçün yeni `ApplicationContext.
session()` açılır və commit edilir; kontrollerə istinad da saxlanmır (siqnal
bağlamalarının `lambda`-larında yaşayır, ekranla birlikdə ölür).

──────────────────────────────────────────────────────────────────────────────
`import_employees()`-DƏN SONRAKI SONUNCU `session.commit()` NİYƏ MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
`BulkEmployeeImportUseCase.import_employees()` DAXİLİNDƏ hər sətirdən sonra
artıq `uow.commit()`/`rollback()` baş verir (bax `composition.py::
_bulk_create_employee_row`) — yəni yaradılmış işçilər HƏR HALDA qalıcıdır.
LAKİN yekun `bulk_log.finish()` + AQREQAT audit sətri (`BULK_EMPLOYEE_IMPORT_
COMPLETED`) HƏMİN sessiyanın SONUNCU, HƏLƏ AÇIQ tranzaksiyasındadır (bax
`bulk_operations.py` başlığı, "TRANZAKSİYA SƏRHƏDİ"). Bu fayldakı
`_on_import()` `session.commit()` çağırmasa, proses burada çöksə belə — yaxud
sadəcə unudulsa belə — yaradılmış işçilər QALIR, `bulk_import_log` sətri isə
`finished_at IS NULL` ("yarımçıq") olaraq QALMAĞA DAVAM EDİR: Root panelində
"kim, neçə sətir idxal etdi?" sualının CAVABI itir, halbuki İŞÇİLƏRİN ÖZÜ
itmir. Bu, CLAUDE.md §5-in "audit yazısı istisna udmur" qaydasının GUI
tərəfidir — ona görə həmin sətir aşağıda AYRICA şərhlənib.

──────────────────────────────────────────────────────────────────────────────
MÜVƏQQƏTİ ŞİFRƏ BU FAYLDA HEÇ BİR SAHƏDƏ SAXLANMIR
──────────────────────────────────────────────────────────────────────────────
`_on_import()` `report`-u YALNIZ `_show_result()`-ə ötürür, `_show_result()`
isə `BulkImportResultDialog`-u qurub `exec()` edir və HEÇ BİR `self.` atributuna
yazmır. Dialoq bağlanan kimi (`WA_DeleteOnClose`, bax `screens/bulk_
operations.py`) `report.created[].temporary_password` daşıyan bütün Python
obyektləri çöp yığılır — bu kontroller siniflərinin YAŞAM MÜDDƏTİ (ekranla
birlikdə) şifrələrin yaşam müddətindən (bir dialoqun `exec()` çağırışı) qəsdən
QISA SAXLANMIR, əksinə şifrənin yaşam müddəti ONDAN da QISADIR.

──────────────────────────────────────────────────────────────────────────────
MAĞAZA ŞABLONU: `config_snapshot` KONTROLLER TƏRƏFİNDƏN OXUNUR
──────────────────────────────────────────────────────────────────────────────
`_submit_capture()` istifadəçidən sərbəst "ayar" mətni QƏBUL ETMİR — `_capture_
snapshot()` mənbə mağazanın AKTİV işçilərinin rollarını birbaşa `employees`/
`positions` CƏDVƏLLƏRİNDƏN oxuyur (bax `bulk_operations.py` use case başlığı:
"çağıran tərəfin ... TƏQDİM ETDİYİ ayar lüğəti"). Bu, `fine_entry.py::
_employee_names` və `announcements.py::_store_choices` ilə EYNİ naxışdır:
domen tipini tanımayan SADƏ SQL sorğusu, `tenant_id` şərti İKİNCİ təcrid qatı
kimi (CLAUDE.md §6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import StoreId, StoreTemplateId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.application.use_cases.bulk_operations import (
        BulkImportPreview,
        BulkImportReport,
    )
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.store_templates import StoreTemplate
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.bulk_operations import BulkOperationsScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `_on_import`-un naməlum xəta halında göstərdiyi ümumi mesaj — XAM istisna
#: mətni istifadəçiyə heç vaxt çatmır (CLAUDE.md-nin bütün kontrollerdə
#: təkrarlanan qaydası).
_GENERIC_IMPORT_ERROR = "İdxal tamamlanmadı. Yenidən cəhd edin."


class BulkOperationsController:
    """ "Toplu Əməliyyatlar" ekranını `BulkEmployeeImportUseCase` və
    `StoreTemplateUseCase`-ə bağlayır."""

    def __init__(
        self, context: ApplicationContext, actor: Employee, *, executor: Any = None
    ) -> None:
        self._context = context
        self._actor = actor
        #: Fon icraçısı — istehsalatda Qt hovuzu, testlərdə `InlineExecutor`.
        self._executor = executor
        #: Qaçan işə istinad: nəticə gəlməmiş toplanarsa siqnal itərdi.
        self._task: Any = None

    def attach(self, screen: BulkOperationsScreen) -> None:
        screen.preview_requested.connect(lambda path: self._on_preview(screen, path))
        screen.import_requested.connect(lambda path: self._on_import(screen, path))
        screen.capture_requested.connect(lambda: self._on_capture(screen))
        screen.apply_requested.connect(lambda template_id: self._on_apply(screen, template_id))
        screen.deactivate_requested.connect(
            lambda template_id: self._on_deactivate(screen, template_id)
        )
        self.refresh_templates(screen)

    # ------------------------------ şablon siyahısı --------------------------- #

    def refresh_templates(self, screen: BulkOperationsScreen) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                templates = session.store_templates.list_templates(
                    tenant_id=session.tenant_id, actor=self._actor, include_inactive=True
                )
                rows = _to_template_rows(session, templates)
                session.commit()
        except KompasOSError as error:
            screen.set_templates([])
            screen.set_template_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("BULK_TEMPLATE_LIST_FAILED")
            screen.set_templates([])
            screen.set_template_message("Şablon siyahısı oxunmadı. Yenidən cəhd edin.", error=True)
            return
        screen.set_templates(rows)

    # -------------------------------- CSV idxalı ------------------------------- #

    def _on_preview(self, screen: BulkOperationsScreen, file_path: str) -> None:
        """CSV önizləməsi — FON SAPINDA.

        Fayl minlərlə sətir ola bilər və hər sətir üçün doğrulama işləyir;
        GUI sapında bu, saniyələrlə donma deməkdir.
        """
        content = self._read_file(screen, file_path)
        if content is None:
            return

        def job() -> object:
            with self._context.session(user_id=self._actor.id) as session:
                preview = session.bulk_employee_import.preview_csv(
                    tenant_id=session.tenant_id, actor=self._actor, csv_bytes=content
                )
                session.commit()
            return _preview_payload(preview)

        def succeeded(payload: Any) -> None:
            screen.set_preview(
                total_rows=payload.total_rows,
                valid_count=payload.valid_count,
                error_count=payload.error_count,
                errors=payload.errors,
                truncated_extra=payload.truncated_extra,
            )

        self._run(
            screen,
            job,
            on_success=succeeded,
            name="BULK_PREVIEW",
            fallback="Fayl önizlənmədi. Yenidən cəhd edin.",
            log_key="BULK_IMPORT_PREVIEW_FAILED",
        )

    def _on_import(self, screen: BulkOperationsScreen, file_path: str) -> None:
        """CSV idxalı — FON SAPINDA (ən uzun əməliyyat).

        Hər sətir üçün ayrıca yazı və commit gedir (bax modul başlığı), yəni
        min sətirlik fayl dəqiqələrlə çəkə bilər. Nəticə dialoqu isə GUI
        sapında açılır — Qt dialoqu yalnız orada təhlükəsizdir.
        """
        content = self._read_file(screen, file_path)
        if content is None:
            return

        def job() -> object:
            with self._context.session(user_id=self._actor.id) as session:
                report = session.bulk_employee_import.import_employees(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    csv_bytes=content,
                    file_ref=file_path,
                )
                # BAX MODUL BAŞLIĞI — sətir-sətir commit ARTIQ baş verib, bu
                # çağırış YALNIZ yekun `bulk_log.finish()` + audit sətrini yazır.
                session.commit()
                limit = int(
                    session.limits.get_int(
                        session.tenant_id,
                        SystemLimitKey.BULK_IMPORT_PREVIEW_ERROR_LIMIT.value,
                        int(DEFAULT_LIMITS[SystemLimitKey.BULK_IMPORT_PREVIEW_ERROR_LIMIT]),
                    )
                )
            return (report, limit)

        def succeeded(result: Any) -> None:
            report, limit = result
            self._show_result(screen, report, preview_error_limit=limit)
            # İdxal BİTİB — növbəti yükləmə üçün formanı TAM sıfırlayır (bax
            # `screens/bulk_operations.py::clear_preview`).
            screen.clear_preview()

        self._run(
            screen,
            job,
            on_success=succeeded,
            name="BULK_IMPORT",
            fallback=_GENERIC_IMPORT_ERROR,
            log_key="BULK_IMPORT_FAILED",
        )

    def _run(
        self,
        screen: BulkOperationsScreen,
        job: Any,
        *,
        on_success: Any,
        name: str,
        fallback: str,
        log_key: str,
    ) -> None:
        """Ortaq icra qabığı — iş fonda, nəticə və xəta GUI sapında."""
        from src.presentation.background_task import run_job  # noqa: PLC0415

        def failed(error: BaseException) -> None:
            if isinstance(error, KompasOSError):
                screen.set_import_message(error.user_message, error=True)
                return
            _error_log.error(log_key, exc_info=error)
            screen.set_import_message(fallback, error=True)

        self._task = run_job(
            job,
            on_success=on_success,
            on_failure=failed,
            owner=screen,
            name=name,
            executor=self._executor,
        )

    def _show_result(
        self,
        screen: BulkOperationsScreen,
        report: BulkImportReport,
        *,
        preview_error_limit: int,
    ) -> None:
        from src.presentation.screens.bulk_operations import (  # noqa: PLC0415
            BulkImportResultDialog,
        )

        payload = _result_payload(report, limit=preview_error_limit)
        dialog = BulkImportResultDialog(
            screen.theme,
            success_count=payload.success_count,
            error_count=payload.error_count,
            errors=payload.errors,
            truncated_extra=payload.truncated_extra,
            created=payload.created,
            parent=screen,
        )
        dialog.exec()

    def _read_file(self, screen: BulkOperationsScreen, file_path: str) -> bytes | None:
        if not file_path:
            screen.set_import_message("Zəhmət olmasa əvvəlcə CSV faylı seçin.", error=True)
            return None
        try:
            return Path(file_path).read_bytes()
        except OSError:
            screen.set_import_message(
                "Fayl oxunmadı — silinmiş və ya köçürülmüş ola bilər. Yenidən seçin.",
                error=True,
            )
            return None

    # ----------------------------- mağaza şablonu ------------------------------ #

    def _on_capture(self, screen: BulkOperationsScreen) -> None:
        from src.presentation.screens.bulk_operations import (  # noqa: PLC0415
            StoreTemplateCaptureDialog,
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                stores = _store_choices(session)
        except Exception:
            _error_log.exception("BULK_TEMPLATE_STORE_LIST_FAILED")
            screen.set_template_message("Mağaza siyahısı oxunmadı. Yenidən cəhd edin.", error=True)
            return
        if not stores:
            screen.set_template_message(
                "Aktiv mağaza tapılmadı — şablon çıxarmaq üçün ən azı bir mağaza olmalıdır.",
                error=True,
            )
            return

        dialog = StoreTemplateCaptureDialog(screen.theme, stores=stores, parent=screen)
        dialog.submitted.connect(
            lambda name, source_store_id: self._submit_capture(screen, name, source_store_id)
        )
        dialog.exec()

    def _submit_capture(
        self, screen: BulkOperationsScreen, name: str, source_store_id: str
    ) -> None:
        try:
            store_id = StoreId(uuid.UUID(source_store_id))
        except ValueError:
            screen.set_template_message("Seçilmiş mağaza identifikatoru düzgün deyil.", error=True)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                snapshot = _capture_snapshot(session, store_id)
                session.store_templates.capture(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    name=name,
                    source_store_id=store_id,
                    config_snapshot=snapshot,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_template_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("BULK_TEMPLATE_CAPTURE_FAILED")
            screen.set_template_message("Şablon yaradılmadı. Yenidən cəhd edin.", error=True)
            return

        self.refresh_templates(screen)

    def _on_apply(self, screen: BulkOperationsScreen, template_id_text: str) -> None:
        from src.presentation.screens.bulk_operations import (  # noqa: PLC0415
            StoreTemplateApplyDialog,
        )

        try:
            template_id = StoreTemplateId(uuid.UUID(template_id_text))
        except ValueError:
            screen.set_template_message("Şablon identifikatoru düzgün deyil.", error=True)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                templates = session.store_templates.list_templates(
                    tenant_id=session.tenant_id, actor=self._actor, include_inactive=True
                )
        except KompasOSError as error:
            screen.set_template_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("BULK_TEMPLATE_APPLY_LOAD_FAILED")
            screen.set_template_message("Şablon oxunmadı. Yenidən cəhd edin.", error=True)
            return

        template = next((t for t in templates if t.store_template_id == template_id), None)
        if template is None:
            screen.set_template_message(
                "Bu şablon artıq mövcud deyil — siyahı yeniləndi.", error=True
            )
            self.refresh_templates(screen)
            return

        dialog = StoreTemplateApplyDialog(
            screen.theme,
            template_name=template.name,
            snapshot_summary=_format_snapshot(template.config_snapshot),
            parent=screen,
        )
        dialog.submitted.connect(
            lambda code, store_name, brand, address: self._submit_apply(
                screen, template_id, code=code, name=store_name, brand=brand, address=address
            )
        )
        dialog.exec()

    def _submit_apply(
        self,
        screen: BulkOperationsScreen,
        template_id: StoreTemplateId,
        *,
        code: str,
        name: str,
        brand: str,
        address: str,
    ) -> None:
        from src.application.use_cases.first_run_setup import StoreDraft  # noqa: PLC0415

        try:
            with self._context.session(user_id=self._actor.id) as session:
                result = session.store_templates.apply(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    template_id=template_id,
                    new_store=StoreDraft(code=code, name=name, brand=brand, address=address),
                )
                session.commit()
        except KompasOSError as error:
            screen.set_template_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("BULK_TEMPLATE_APPLY_FAILED")
            screen.set_template_message("Yeni mağaza yaradılmadı. Yenidən cəhd edin.", error=True)
            return

        screen.set_template_message(
            f"«{result.template_name}» şablonu əsasında yeni mağaza yaradıldı: {name} ({code})."
        )
        self.refresh_templates(screen)

    def _on_deactivate(self, screen: BulkOperationsScreen, template_id_text: str) -> None:
        try:
            template_id = StoreTemplateId(uuid.UUID(template_id_text))
        except ValueError:
            screen.set_template_message("Şablon identifikatoru düzgün deyil.", error=True)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.store_templates.deactivate(
                    tenant_id=session.tenant_id, actor=self._actor, template_id=template_id
                )
                session.commit()
        except KompasOSError as error:
            screen.set_template_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("BULK_TEMPLATE_DEACTIVATE_FAILED")
            screen.set_template_message("Şablon deaktiv edilmədi. Yenidən cəhd edin.", error=True)
            return

        self.refresh_templates(screen)


# --------------------------------------------------------------------------- #
# Köməkçilər — Qt TƏLƏB ETMİR, birbaşa test oluna bilir
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _PreviewPayload:
    """`_preview_payload()`-un nəticəsi — sahələr `BulkOperationsScreen.
    set_preview()`-in imzası ilə HƏRFİ-HƏRFİNƏ EYNİDİR.

    Sözlük (`dict[str, object]`) ƏVƏZİNƏ dataclass: `**payload` açılışı mypy
    strict rejimində `object`-ə düşür və çağırış yerindəki `int`/`list[dict]`
    tələbini yoxlaya bilmir (bax `preview_screens.py::_dashboard` başlığındakı
    eyni qərar — "sahələr AÇIQ yazılır").
    """

    total_rows: int
    valid_count: int
    error_count: int
    errors: list[dict[str, str]]
    truncated_extra: int


def _preview_payload(preview: BulkImportPreview) -> _PreviewPayload:
    """`BulkImportPreview` → `BulkOperationsScreen.set_preview(...)` arqumentləri."""
    return _PreviewPayload(
        total_rows=preview.total_data_rows,
        valid_count=len(preview.valid_rows),
        error_count=preview.error_count,
        errors=[
            {"row": str(item.row_number), "message": item.message}
            for item in preview.displayed_errors
        ],
        truncated_extra=(
            preview.error_count - len(preview.displayed_errors) if preview.errors_truncated else 0
        ),
    )


@dataclass(frozen=True)
class _ResultPayload:
    """`_result_payload()`-un nəticəsi — bax `_PreviewPayload` başlığı."""

    success_count: int
    error_count: int
    errors: list[dict[str, str]]
    truncated_extra: int
    created: list[dict[str, str]]


def _result_payload(report: BulkImportReport, *, limit: int) -> _ResultPayload:
    """`BulkImportReport` → `BulkImportResultDialog(...)` arqumentləri.

    `report.errors` (bütün TƏHLİL + YARADILMA xətaları) `preview_csv`-in
    göstərdiyindən DAHA GENİŞ ola bilər (sətir yaratma anında da uğursuzluq
    baş verə bilər, bax `bulk_operations.py::import_employees`) — ona görə
    ekran limiti BURADA TƏKRAR tətbiq olunur, eyni ROOT açarı ilə
    (`BULK_IMPORT_PREVIEW_ERROR_LIMIT`) — ikinci, ayrıca limit açarı YARADILMIR.
    """
    shown = report.errors[: max(1, limit)]
    return _ResultPayload(
        success_count=report.success_count,
        error_count=report.error_count,
        errors=[{"row": str(item.row_number), "message": item.message} for item in shown],
        truncated_extra=max(0, len(report.errors) - len(shown)),
        created=[
            {"username": item.username, "temporary_password": item.temporary_password}
            for item in report.created
        ],
    )


def _to_template_rows(session: Session, templates: list[StoreTemplate]) -> list[dict[str, str]]:
    """`StoreTemplate` siyahısı → `BulkOperationsScreen.set_templates(...)` sətirləri."""
    store_ids = [t.based_on_store_id for t in templates if t.based_on_store_id is not None]
    names = _store_names(session, store_ids) if store_ids else {}
    rows: list[dict[str, str]] = []
    for template in templates:
        source_name = "—"
        if template.based_on_store_id is not None:
            source_name = names.get(template.based_on_store_id, "Silinmiş mağaza")
        captured_at = str(template.config_snapshot.get("captured_at", ""))
        rows.append(
            {
                "id": str(template.store_template_id),
                "name": template.name,
                "source_store": source_name,
                "setting_count": str(len(template.config_snapshot)),
                "captured_at": captured_at[:10],
                "status": "Aktiv" if template.is_active else "Deaktiv",
            }
        )
    return rows


def _format_snapshot(snapshot: Mapping[str, object]) -> str:
    """`config_snapshot["positions"]` → tətbiq dialoqunda göstərilən İSTİNAD mətni."""
    positions = snapshot.get("positions")
    if isinstance(positions, list) and positions:
        return ", ".join(str(item) for item in positions)
    return "Bu şablonda rol məlumatı saxlanmayıb."


def _store_names(session: Session, store_ids: list[Any]) -> dict[Any, str]:
    """`fine_entry.py::_store_names` ilə EYNİ naxış — bu kontroller ÖZ nüsxəsini saxlayır."""
    if not store_ids:
        return {}
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND id = ANY(%s)",
        (session.tenant_id, list(store_ids)),
    ).fetchall()
    return {row["id"]: str(row["name"]) for row in rows}


def _store_choices(session: Session) -> list[tuple[str, str]]:
    """`announcements.py::_store_choices` ilə EYNİ naxış — bu kontroller ÖZ nüsxəsini saxlayır."""
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows]


def _capture_snapshot(session: Session, store_id: StoreId) -> dict[str, object]:
    """Mənbə mağazanın AD-ı + AKTİV işçilərinin İSTİFADƏ ETDİYİ rolların adları.

    Yalnız İNFORMATİV məzmundur (bax modul başlığı) — heç bir kataloq YENİDƏN
    YARADILMIR, `apply()` bu dəyəri OXUMUR, yalnız DAŞIYIR (`StoreTemplate.
    config_snapshot` başlığı).
    """
    store_row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE tenant_id = %s AND id = %s",
        (session.tenant_id, store_id),
    ).fetchone()
    position_rows = session.uow.connection.execute(
        """
        SELECT DISTINCT p.name_az
          FROM employees e
          JOIN positions p ON p.id = e.position_id
         WHERE e.tenant_id = %s AND e.store_id = %s AND e.is_active
         ORDER BY p.name_az
        """,
        (session.tenant_id, store_id),
    ).fetchall()
    return {
        "store_name": str(store_row["name"]) if store_row else "",
        "positions": [str(row["name_az"]) for row in position_rows],
    }


__all__ = ["BulkOperationsController"]
