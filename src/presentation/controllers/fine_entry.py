"""Manual cərimə qeydiyyatının yazı yolu + sübut şəklinin növbəyə düşməsi.

──────────────────────────────────────────────────────────────────────────────
SIRA: ƏVVƏLCƏ ŞƏKİL DİSKƏ, SONRA CƏRİMƏ BAZAYA
──────────────────────────────────────────────────────────────────────────────
`EvidenceUploadQueue.enqueue()` faylı LOKAL diskə yazır (şəbəkə yoxdur) və
növbə açarını qaytarır; həmin açar cəriməyə `evidence_reference` kimi gedir.

Tərsi olsaydı — əvvəlcə cərimə, sonra spool — aradakı çökmə "sübutu olmayan
cərimə" yaradardı. Bölmə 4 isə manual cəriməni sübutsuz QADAĞAN edir, yəni
belə sətir bərpa oluna bilməyən pozuntudur. Bu sıra ilə ən pis hal "sahibsiz
spool faylı"dır: yer tutur, heç kimə zərər vermir, növbəti yükləmə dövrəsində
sahibi tapılmayan qeyd kimi jurnala düşür.

Ona görə `fine_id` ƏVVƏLCƏDƏN yaradılır və use case-ə ötürülür
(`ManualFineUseCase.issue(fine_id=...)`) — növbə sətri `fine_id` tələb edir,
cərimə isə növbə açarını; biri digərini gözləsəydi dövrə bağlanardı.

──────────────────────────────────────────────────────────────────────────────
DROPDOWN-LAR AD GÖSTƏRİR, USE CASE ID İSTƏYİR
──────────────────────────────────────────────────────────────────────────────
Ekran domen tiplərini tanımır (bax `controllers/__init__.py`), ona görə
seçimləri MƏTN kimi verir. Ad→ID xəritəsi `options()` çağırışında qurulur və
kontrollerdə saxlanılır. Xəritə boşdursa forma göndərilə bilməz — bu, səssiz
"yanlış işçiyə cərimə" halının qarşısını alır.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_b import FineEntryScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Dropdown seçimləri boş olduqda ekranda göstərilən səbəb.
NO_STORES_MESSAGE = "Sizə hələ mağaza təyin edilməyib — cərimə yarada bilməzsiniz."


class FineEntryController:
    """Cərimə formasını `ManualFineUseCase` və sübut növbəsinə bağlayır."""

    def __init__(
        self, context: ApplicationContext, actor: Employee, *, executor: Any = None
    ) -> None:
        self._context = context
        self._actor = actor
        self._fine_types: dict[str, Any] = {}
        self._stores: dict[str, Any] = {}
        self._employees: dict[str, Any] = {}
        #: Fon icraçısı — istehsalatda Qt hovuzu, testlərdə `InlineExecutor`.
        self._executor = executor
        #: Ehtiyat: əsas iş bitmədən toplanmasın (bax `_trigger_evidence_upload`).
        self._upload_task: Any = None

    # ------------------------------- seçimlər -------------------------------- #

    def options(self) -> tuple[list[str], list[str], list[str]]:
        """(cərimə növləri, mağazalar, işçilər) — ekran KONSTRUKTORU üçün.

        Boş siyahı qaytarmaq normal haldır: təyinatsız operator heç nə görmür
        (bax `ManualFineUseCase.allowed_stores` — eyni fail-safe istiqamət).
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                self._fine_types = {
                    fine_type.name: fine_type.fine_type_id
                    for fine_type in session.manual_fines.selectable_fine_types(session.tenant_id)
                    if fine_type.fine_type_id is not None
                }
                store_ids = session.manual_fines.allowed_stores(self._actor)
                self._stores = _store_names(session, store_ids)
                self._employees = _employee_names(session, store_ids)
        except Exception:
            _error_log.exception("FINE_OPTIONS_LOAD_FAILED")
            self._fine_types, self._stores, self._employees = {}, {}, {}

        return (
            sorted(self._fine_types),
            sorted(self._stores),
            sorted(self._employees),
        )

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: FineEntryScreen) -> None:
        screen.submitted.connect(lambda payload: self._on_submitted(screen, payload))

    def _on_submitted(self, screen: FineEntryScreen, payload: Any) -> None:
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return
        if not self._stores:
            screen.show_error(title="Cərimə yaradıla bilmədi", message=NO_STORES_MESSAGE)
            return

        fine_type_id = self._fine_types.get(str(payload.get("fine_type", "")).strip())
        store_id = self._stores.get(str(payload.get("store", "")).strip())
        employee_id = self._employees.get(str(payload.get("employee", "")).strip())
        if fine_type_id is None or store_id is None or employee_id is None:
            screen.show_error(
                title="Forma tamamlanmayıb",
                message="Cərimə növü, mağaza və işçi seçilməlidir.",
            )
            return

        photo = Path(str(payload.get("photo_path", "")))
        try:
            content = photo.read_bytes()
        except OSError:
            screen.show_error(
                title="Şəkil oxunmadı",
                message="Seçilmiş foto faylı açıla bilmədi. Yenidən seçin.",
            )
            return

        self._issue(
            screen,
            fine_type_id=fine_type_id,
            store_id=store_id,
            employee_id=employee_id,
            filename=photo.name,
            content=content,
        )

    def _issue(
        self,
        screen: FineEntryScreen,
        *,
        fine_type_id: Any,
        store_id: Any,
        employee_id: Any,
        filename: str,
        content: bytes,
    ) -> None:
        from src.domain.value_objects.identifiers import new_fine_id  # noqa: PLC0415
        from src.infrastructure.storage.upload_queue import UploadOwnerType  # noqa: PLC0415

        fine_id = new_fine_id()
        taken_at = datetime.now(UTC)

        try:
            # 1) Şəkil diskə — bax modul başlığındakı sıra izahı.
            # `owner_type`/`owner_id` #17-də (Faza 7) ÜMUMİLƏŞDİRİLDİ — cərimə
            # sübutu artıq növbənin YEGANƏ sahibi deyil (bax `upload_queue.py`
            # başlığı), lakin bu axının ÖZÜ dəyişmir.
            entry_id = self._context.evidence_queue().enqueue(
                tenant_id=str(self._context.tenant_id),
                owner_type=UploadOwnerType.FINE,
                owner_id=str(fine_id),
                store_id=store_id,
                filename=filename,
                content=content,
                taken_at=taken_at,
            )
            # 2) Cərimə bazaya — sübut istinadı hələlik növbə açarıdır.
            with self._context.session(user_id=self._actor.id) as session:
                session.manual_fines.issue(
                    tenant_id=session.tenant_id,
                    operator=self._actor,
                    employee_id=employee_id,
                    store_id=store_id,
                    fine_type_id=fine_type_id,
                    evidence_reference=entry_id,
                    fine_id=fine_id,
                )
                session.uow.fines.mark_evidence_pending(fine_id)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Cərimə yaradılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("MANUAL_FINE_FAILED", extra={"fine_id": str(fine_id)})
            screen.show_error(
                title="Cərimə yaradılmadı",
                message="Qeyd saxlanmadı. Yenidən cəhd edin.",
            )
            return

        # 3) Yükləməni DƏRHAL bir dəfə sınayırıq — şəbəkə varsa şəkil saniyələr
        #    içində Drive-a düşür. Uğursuzluq əhəmiyyətsizdir: element növbədə
        #    qalır və taymer onu təkrar götürür.
        self._trigger_evidence_upload(screen)
        self._refresh(screen)

    def _trigger_evidence_upload(self, screen: FineEntryScreen) -> None:
        """`run_evidence_uploads()` FON SAPINDA — DÖVRƏ 5 AUDİTİNİN TAPINTISI.

        ──────────────────────────────────────────────────────────────────────
        ƏVVƏL SİNXRON İDİ
        ──────────────────────────────────────────────────────────────────────
        `run_evidence_uploads()` növbədəki HƏR gözləyən şəkli (partiya ölçüsü
        20-yə qədər) Google Drive-a yükləyir — bu tək YENİ şəkil deyil, bütün
        BACKLOG-dur (zəif internetli filialda toplanmış ola bilər). `app.py::
        _drain_upload_queue` (D3-01) məhz bu funksiyanı GUI sapından çıxarıb,
        lakin bu çağırış nöqtəsi o zaman unudulmuşdu — "cərimə saxla" düyməsi
        arxada eyni sinxron şəbəkə yükləməsini yenə DÖVRƏ EDİRDİ.
        """
        from src.presentation.background_task import run_job  # noqa: PLC0415

        self._upload_task = run_job(
            self._context.run_evidence_uploads,
            on_success=lambda _uploaded: None,
            on_failure=lambda error: _error_log.error(
                "FINE_EVIDENCE_UPLOAD_TRIGGER_FAILED", exc_info=error
            ),
            owner=screen,
            name="FINE_EVIDENCE_UPLOAD",
            executor=self._executor,
        )

    def _refresh(self, screen: FineEntryScreen) -> None:
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        ScreenDataBinder(self._context, self._actor).populate("fines", screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _store_names(session: Any, store_ids: list[Any]) -> dict[str, Any]:
    if not store_ids:
        return {}
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND id = ANY(%s) ORDER BY name",
        (session.tenant_id, list(store_ids)),
    ).fetchall()
    return {str(row["name"]): row["id"] for row in rows}


def _employee_names(session: Any, store_ids: list[Any]) -> dict[str, Any]:
    """Yalnız operatorun izlədiyi filiallardakı AKTİV işçilər.

    Süzgəc scope ilə eynidir: `ManualFineUseCase._require_store_scope` onsuz da
    kənar filialı rədd edir, lakin dropdown-da görünüb sonra rədd edilmək
    operatoru çaşdırardı — görünən hər şey seçilə bilməlidir.
    """
    if not store_ids:
        return {}
    rows = session.uow.connection.execute(
        """
        SELECT id, first_name, last_name
          FROM employees
         WHERE tenant_id = %s AND is_active AND store_id = ANY(%s)
         ORDER BY last_name, first_name
         LIMIT 500
        """,
        (session.tenant_id, list(store_ids)),
    ).fetchall()
    return {f"{row['first_name']} {row['last_name']}".strip(): row["id"] for row in rows}


__all__ = ["NO_STORES_MESSAGE", "FineEntryController"]
