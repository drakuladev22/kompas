"""Sahə hesabatlarının YAZI yolu — #26 + #27 (kompas1.md Faza 3).

`FieldReportScreen` HƏM oxuyur (açıq hesabatlar), HƏM yazır (təqdim et /
icraya götür / bağla) — CLAUDE.md §6-ya görə belə ekranın ÖZ kontrolleri olur,
`screen_data.py`-a bağlanmır. Sessiya SAXLANILMIR: hər əməliyyat üçün yenisi
açılır və commit edilir; hər yazıdan sonra siyahı YENİDƏN oxunur (`refresh`).

──────────────────────────────────────────────────────────────────────────────
BİR KONTROLLER, İKİ MENYU AÇARI — `if report_type == ...` YOXDUR
──────────────────────────────────────────────────────────────────────────────
Menyuda iki maddə var («Mağaza Auditi», «İnsident Bildirişi»), lakin onların
fərqi ŞABLON KODU DEYİL, kataloqun `requires_checklist` XASSƏSİDİR (bax
`use_cases/field_reports.py` "Struktur Qərar A"). Ona görə burada şablon
kodlarının lüğəti YOXDUR — `SCREEN_TEMPLATE_FAMILY` yalnız EKRAN AÇARINI
həmin XASSƏYƏ bağlayır:

    "store_audit"      → requires_checklist = True
    "incident_report"  → requires_checklist = False

Kataloqa üçüncü şablon əlavə olunanda (`INSERT`) o, avtomatik olaraq öz
ailəsinin ekranında görünür və bu fayl DƏYİŞMİR. Eyni naxış üç kataloq ekranı
üçün artıq var (`controllers/catalog_admin.py` — bir kontroller, üç açar).

──────────────────────────────────────────────────────────────────────────────
SƏLAHİYYƏT BURADA TƏKRARLANMIR
──────────────────────────────────────────────────────────────────────────────
`can_conduct_store_audit` / `can_report_incident` yoxlaması use case-in
İÇİNDƏDİR (`_flag_for`, `_require`). Kontrollerin əlavəsi yalnız istisnanın
İSTİFADƏÇİYƏ İZAH EDİLMƏSİDİR (`controllers/employee_documents.py`-dəki eyni
qərar).

BİR İSTİSNA HALI QƏSDƏN TUTULUR: `list_open` HƏMİŞƏ `can_conduct_store_audit`
tələb edir (038: "bildirmək sərbəstdir, HƏLL ETMƏK deyil"), yəni yalnız
`can_report_incident` daşıyan `Satıcı` insident FORMASINI görür, SİYAHINI isə
yox. Bu, xəta DEYİL — gözlənilən vəziyyətdir, ona görə ekran qırmızı xəta
əvəzinə izah sətri alır (`set_list_notice`).

──────────────────────────────────────────────────────────────────────────────
FOTO SIRASI — `fine_entry.py`-DAN NİYƏ FƏRQLİDİR
──────────────────────────────────────────────────────────────────────────────
Cərimədə `fine_id` ƏVVƏLCƏDƏN yaradılır, ona görə şəkil BAZADAN ƏVVƏL növbəyə
düşür. Sahə hesabatında bu mümkün deyil: `report_id` və bənd İD-ləri
`FieldReportUseCase.submit()`-in İÇİNDƏ yaranır (`new_field_report_id()`), yəni
növbənin `owner_id`-si təqdimatdan ƏVVƏL mövcud deyil.

Ona görə sıra belədir:

    1. fayllar DİSKDƏN oxunur          (yararsız fayl hesabat yazılmadan tutulur)
    2. `validate_evidence_payload`     (SEC-018 — YALNIZ şəkil, PDF YOX)
    3. `submit()` + commit
    4. şəkillər növbəyə düşür          (`owner_id` = hesabat / bənd İD-si)
    5. `run_evidence_uploads()`

2-ci addım KRİTİKDİR: onsuz yararsız fayl hesabat YAZILDIQDAN sonra rədd
edilər və bənd "şəkli var" deyib duran, lakin heç vaxt yüklənməyəcək bir
istinadla qalardı.

FOTO TƏLƏB EDƏN BƏNDİN MÜVƏQQƏTİ İSTİNADI: domen cavablanmış bəndi şəkilsiz
qəbul etmir (`_apply_answer`), Drive istinadı isə yalnız yükləmə bitəndə
məlum olur. Ona görə təqdimat anında `PENDING_PHOTO_PREFIX` ilə başlayan
müvəqqəti istinad yazılır və `attach_uploaded_photo` onu həqiqi istinadla ƏVƏZ
EDİR (`FieldReportChecklistItem.attach_photo` üzərinə yazır, əlavə etmir).
Hesabat səviyyəsindəki şəkillərdə isə müvəqqəti istinad YAZILMIR — orada
`add_photo` ƏLAVƏ edir, yəni müvəqqəti sətir Drive istinadının yanında ilişib
qalardı.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from src.application.use_cases.field_reports import FieldReportDraft
from src.domain.entities.field_report import SCHEMA_MIN_DETAIL_LENGTH
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.field_reports import ChecklistItemDraft, FieldReportStatus
from src.domain.value_objects.identifiers import FieldReportId, StoreId
from src.presentation.screens.field_reports import FieldReportFormValues
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.field_reports import FieldReportSubmission
    from src.domain.entities.employee import Employee
    from src.domain.entities.field_report import FieldReport
    from src.domain.value_objects.field_reports import FieldReportCategory, FieldReportTemplate
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.field_reports import ChecklistEntry, FieldReportScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Ekran açarı → şablon ailəsi (`requires_checklist`). Bax modul başlığı:
#: burada ŞABLON KODU yoxdur və olmamalıdır.
SCREEN_TEMPLATE_FAMILY: Final[dict[str, bool]] = {
    "store_audit": True,
    "incident_report": False,
}

#: Foto tələb edən bəndin TƏQDİMAT anındakı müvəqqəti istinad prefiksi.
#: Həqiqi Drive istinadı yükləmə bitəndə üzərinə yazılır (bax modul başlığı).
PENDING_PHOTO_PREFIX: Final = "queue-pending:"

#: `list_open` səlahiyyət tələb etdikdə göstərilən izah — xəta DEYİL.
LIST_RESTRICTED_NOTICE: Final = (
    "Açıq hesabatların siyahısını yalnız audit səlahiyyəti olan rollar görür. "
    "Sizin bildirişiniz yazıldı və məsul komandaya göndərildi."
)


class FieldReportsController:
    """`FieldReportScreen`-i `FieldReportUseCase`-ə bağlayır."""

    def __init__(
        self, context: ApplicationContext, actor: Employee, *, requires_checklist: bool
    ) -> None:
        self._context = context
        self._actor = actor
        self._requires_checklist = requires_checklist

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: FieldReportScreen) -> None:
        """Siqnalları bağlayır və ekranı ilk dəfə doldurur."""
        screen.submit_requested.connect(lambda values: self._on_submit(screen, values))
        screen.progress_requested.connect(
            lambda report_id: self._on_progress(screen, str(report_id))
        )
        screen.close_requested.connect(
            lambda report_id, status: self._on_close(screen, str(report_id), str(status))
        )
        self.refresh(screen)

    def refresh(self, screen: FieldReportScreen) -> None:
        """Kataloqu, mağazaları, ROOT parametrlərini və açıq siyahını oxuyur."""
        notice = ""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                templates = [
                    template
                    for template in session.field_reports.list_templates(
                        tenant_id=session.tenant_id, actor=self._actor
                    )
                    if template.requires_checklist is self._requires_checklist
                ]
                categories: list[FieldReportCategory] = []
                for template in templates:
                    categories.extend(
                        session.field_reports.list_categories(
                            tenant_id=session.tenant_id,
                            actor=self._actor,
                            report_type=template.code,
                        )
                    )
                stores = _store_choices(session)
                min_detail = _min_detail_length(session)
                max_photos = _max_photos(session)
                reports, notice = self._open_reports(session, templates)
                names = {template.code: template.name_az for template in templates}
                category_names = {category.code: category.name_az for category in categories}
                rows = [_report_row(session, report, names, category_names) for report in reports]
        except KompasOSError as error:
            # Buraya YALNIZ forma qura bilməyən hal düşür (kataloq oxunmadı) —
            # `list_open`-in səlahiyyət istisnası aşağıda, `_open_reports`-da
            # UDULUR, çünki o, formanı bağlamır.
            screen.show_error(title="Forma açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("FIELD_REPORT_FORM_LOAD_FAILED")
            screen.show_error(
                title="Forma açıla bilmədi",
                message="Kataloq oxunmadı. Yenidən cəhd edin.",
            )
            return

        screen.set_templates([_template_row(template) for template in templates])
        screen.set_categories([_category_row(category) for category in categories])
        screen.set_stores(stores)
        screen.set_detail_min_length(min_detail)
        screen.set_photo_limit(max_photos)
        screen.set_open_reports(rows)
        screen.set_list_notice(notice)

    def _open_reports(
        self, session: Session, templates: list[FieldReportTemplate]
    ) -> tuple[list[FieldReport], str]:
        """Bu ailənin açıq hesabatları.

        ŞABLON ÜZRƏ AYRI SORĞU: `list_open` nəticəni ROOT səhifə ölçüsü ilə
        kəsir, ona görə "hamısını oxu, sonra süz" yolu limitə görə bəzi
        şablonları TAMAM göstərməyə bilərdi.
        """
        reports: list[FieldReport] = []
        for template in templates:
            try:
                reports.extend(
                    session.field_reports.list_open(
                        tenant_id=session.tenant_id,
                        actor=self._actor,
                        report_type=template.code,
                    )
                )
            except KompasOSError:
                # Səlahiyyət yoxdur — gözlənilən haldır (bax modul başlığı).
                return [], LIST_RESTRICTED_NOTICE
        return reports, ""

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_submit(self, screen: FieldReportScreen, values: Any) -> None:
        """«Təqdim Et» — foto sırası modul başlığında izah olunub."""
        if not isinstance(values, FieldReportFormValues):  # pragma: no cover - tip qoruyucusu
            return

        try:
            store_id = StoreId(uuid.UUID(values.store_id))
        except ValueError:
            screen.set_form_message("Mağaza identifikatoru düzgün deyil.", error=True)
            return

        try:
            report_payload = [_read_file(path) for path in values.photo_paths]
            item_payloads = [
                _read_file(entry.photo_path) if entry.photo_path else None
                for entry in values.checklist
            ]
        except OSError:
            screen.set_form_message(
                "Seçilmiş şəkil açıla bilmədi. Faylı yenidən seçin.", error=True
            )
            return

        draft = FieldReportDraft(
            report_type=values.template_code,
            category=values.category_code,
            store_id=store_id,
            detail=values.detail,
            checklist=tuple(_item_draft(entry) for entry in values.checklist),
        )

        try:
            with self._context.session(user_id=self._actor.id) as session:
                max_bytes = session.max_upload_bytes()
                for name, content in [*report_payload, *[p for p in item_payloads if p]]:
                    _validate_photo(content, name, max_bytes=max_bytes)
                submission = session.field_reports.submit(
                    tenant_id=session.tenant_id, actor=self._actor, draft=draft
                )
                report = submission.report
                summary = _submission_summary(submission)
                session.commit()
        except KompasOSError as error:
            screen.set_form_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("FIELD_REPORT_SUBMIT_FAILED")
            screen.set_form_message("Hesabat yazılmadı. Yenidən cəhd edin.", error=True)
            return

        queued = self._enqueue_photos(
            screen,
            report=report,
            store_id=store_id,
            report_payload=report_payload,
            item_payloads=item_payloads,
        )
        screen.clear_form()
        # Növbə uğursuz olubsa mesaj ARTIQ qoyulub və ÜSTÜNDƏN YAZILMIR:
        # "hesabat yazıldı" xülasəsi şəklin itdiyi faktını gizlədərdi.
        if queued:
            screen.set_form_message(summary)
        self.refresh(screen)

    def _enqueue_photos(
        self,
        screen: FieldReportScreen,
        *,
        report: FieldReport,
        store_id: StoreId,
        report_payload: list[tuple[str, bytes]],
        item_payloads: list[tuple[str, bytes] | None],
    ) -> bool:
        """Şəkilləri sübut növbəsinə yazır (`owner_type=FIELD_REPORT`).

        Uğursuzluq HESABATI GERİ QAYTARMIR — sətir ARTIQ yazılıb (bax modul
        başlığı, `employee_documents._enqueue_file` ilə eyni qərar): tapıntının
        özü şəkildən daha vacibdir və şəkil sonradan əlavə edilə bilər.
        """
        owners: list[tuple[str, tuple[str, bytes]]] = [
            (str(report.id), payload) for payload in report_payload
        ]
        # Bəndlərin sırası draft sırasının EYNİSİDİR (`_build_items`
        # `enumerate`-dən istifadə edir), ona görə indeks üzrə uyğunlaşma
        # təhlükəsizdir.
        for item, payload in zip(report.items, item_payloads, strict=False):
            if payload is not None:
                owners.append((str(item.id), payload))
        if not owners:
            return True

        from datetime import UTC, datetime  # noqa: PLC0415

        from src.infrastructure.storage.upload_queue import UploadOwnerType  # noqa: PLC0415

        taken_at = datetime.now(UTC)
        try:
            for owner_id, (filename, content) in owners:
                self._context.evidence_queue().enqueue(
                    tenant_id=str(self._context.tenant_id),
                    owner_type=UploadOwnerType.FIELD_REPORT,
                    owner_id=owner_id,
                    store_id=store_id,
                    filename=filename,
                    content=content,
                    taken_at=taken_at,
                )
        except KompasOSError as error:
            screen.set_form_message(
                f"Hesabat YAZILDI, lakin şəkil növbəyə düşmədi: {error.user_message}", error=True
            )
            return False
        except Exception:
            _error_log.exception(
                "FIELD_REPORT_PHOTO_ENQUEUE_FAILED", extra={"report": str(report.id)}
            )
            screen.set_form_message(
                "Hesabat YAZILDI, lakin şəkillər növbəyə yerləşdirilmədi.", error=True
            )
            return False

        # Yükləməni DƏRHAL bir dəfə sınayırıq (`fine_entry.py`-dəki eyni qərar).
        self._context.run_evidence_uploads()
        return True

    def _on_progress(self, screen: FieldReportScreen, report_id: str) -> None:
        """«İcraya Götür» — `SUBMITTED` → `IN_PROGRESS`."""
        parsed = _parse_report_id(report_id)
        if parsed is None:
            screen.set_list_notice("Hesabat identifikatoru düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.field_reports.start_progress(
                    tenant_id=session.tenant_id, actor=self._actor, report_id=parsed
                )
                session.commit()
        except KompasOSError as error:
            screen.set_list_notice(error.user_message)
            return
        except Exception:
            _error_log.exception("FIELD_REPORT_PROGRESS_FAILED", extra={"report": report_id})
            screen.set_list_notice("Dəyişiklik yazılmadı. Yenidən cəhd edin.")
            return

        self.refresh(screen)

    def _on_close(self, screen: FieldReportScreen, report_id: str, status_value: str) -> None:
        """«Həll Edildi» / «Əsassızdır» — qeyd MƏCBURİDİR (domen qaydası)."""
        parsed = _parse_report_id(report_id)
        if parsed is None:
            screen.set_list_notice("Hesabat identifikatoru düzgün deyil.")
            return
        try:
            status = FieldReportStatus(status_value)
        except ValueError:  # pragma: no cover - siqnal yalnız enum dəyəri göndərir
            screen.set_list_notice("Naməlum bağlanma qərarı.")
            return

        note = self._ask_note(screen, status)
        if note is None:
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.field_reports.close(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    report_id=parsed,
                    status=status,
                    note=note,
                )
                session.commit()
        except KompasOSError as error:
            screen.set_list_notice(error.user_message)
            return
        except Exception:
            _error_log.exception("FIELD_REPORT_CLOSE_FAILED", extra={"report": report_id})
            screen.set_list_notice("Qərar yazılmadı. Yenidən cəhd edin.")
            return

        self.refresh(screen)

    @staticmethod
    def _ask_note(screen: FieldReportScreen, status: FieldReportStatus) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            f"Hesabatı bağla — {status.label_az}",
            "Qərarın izahı (məcburi) — audit jurnalına düşür:",
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _template_row(template: FieldReportTemplate) -> dict[str, str]:
    """`FieldReportTemplate` → ekranın FAKTİKİ gözlədiyi açarlar.

    Açarlar `preview_screens._field_report`-dakı İLƏ EYNİDİR (CLAUDE.md §6) —
    ayrı ad məkanı layihədə artıq bir dəfə gizli qüsur yaradıb (`menu.py`).
    """
    return {
        "code": template.code,
        "name": template.name_az,
        "description": template.description_az or "",
        "requires_checklist": "1" if template.requires_checklist else "0",
    }


def _category_row(category: FieldReportCategory) -> dict[str, str]:
    """`FieldReportCategory` → ekran sətri.

    `route_text` MARŞRUTU İNSAN DİLİNDƏ göstərir: marşrutlanmayan kateqoriya
    (audit) "marşrutlanmır" yazır, çünki boş sətir "hələ yüklənməyib" kimi
    oxuna bilərdi.
    """
    return {
        "code": category.code,
        "template": category.report_type,
        "name": category.name_az,
        "route_text": category.route_to_role or "marşrutlanmır",
    }


def _report_row(
    session: Session,
    report: FieldReport,
    template_names: dict[str, str],
    category_names: dict[str, str],
) -> dict[str, str]:
    """`FieldReport` → siyahı sətri (maket yolu ilə EYNİ açarlar)."""
    score = report.audit_score
    return {
        "id": str(report.id),
        # Kataloqda tapılmayan kod ÖZ KODU ilə göstərilir — soft delete edilmiş
        # şablon keçmiş hesabatı oxunmaz etməməlidir.
        "type_name": template_names.get(report.report_type, report.report_type),
        "category_name": category_names.get(report.category, report.category),
        "store": _store_name(session, report.store_id),
        "detail": report.detail,
        "status": report.status.value,
        "status_text": report.status.label_az,
        # `None` = heç bir bənd cavablanmayıb; "0%" YAZMIRIQ (bax
        # `FieldReport.audit_score` başlığı).
        "score_text": f"{score:.0f}%" if score is not None else "—",
        "date": report.created_at.astimezone().strftime("%d.%m.%Y %H:%M"),
    }


def _item_draft(entry: ChecklistEntry) -> ChecklistItemDraft:
    """Ekran bəndini domen draft-ına çevirir (müvəqqəti foto istinadı ilə)."""
    return ChecklistItemDraft(
        item_text=entry.item_text,
        is_blocking=entry.is_blocking,
        photo_required=entry.photo_required,
        passed=entry.passed,
        photo_ref=(
            f"{PENDING_PHOTO_PREFIX}{Path(entry.photo_path).name}" if entry.photo_path else None
        ),
        note=entry.note.strip() or None,
    )


def _submission_summary(submission: FieldReportSubmission) -> str:
    """Təqdimatın nəticəsi — istifadəçi NƏ BAŞ VERDİYİNİ görməlidir."""
    parts = ["Hesabat yazıldı."]
    tasks = len(submission.corrective_task_ids)
    if tasks:
        parts.append(f"{tasks} düzəliş tapşırığı yaradıldı.")
    role = submission.routed_role
    if role:
        recipients = submission.routed_recipients
        parts.append(
            f"Marşrut: {role} — {recipients} nəfərə bildiriş getdi."
            if recipients
            else f"Marşrut: {role} — həmin rolda aktiv işçi tapılmadı, "
            f"bildiriş audit səlahiyyəti olanlara göndərildi."
        )
    return " ".join(parts)


def _read_file(path: str) -> tuple[str, bytes]:
    """(fayl adı, məzmun). `OSError` QƏSDƏN yuxarı ötürülür — çağıran izah edir."""
    file_path = Path(path)
    return file_path.name, file_path.read_bytes()


def _validate_photo(content: bytes, filename: str, *, max_bytes: int) -> None:
    """SEC-018 ağ siyahısı — qayda TƏK yerdədir (`google_drive.py`).

    Növbənin `enqueue()`-si onsuz da eyni funksiyanı çağırır; burada ONDAN
    ƏVVƏL çağırılır ki, yararsız fayl hesabat YAZILMADAN tutulsun.
    """
    from src.infrastructure.storage.google_drive import (  # noqa: PLC0415
        validate_evidence_payload,
    )
    from src.infrastructure.storage.upload_queue import UploadOwnerType  # noqa: PLC0415

    validate_evidence_payload(
        content, filename, max_bytes=max_bytes, owner_type=UploadOwnerType.FIELD_REPORT.value
    )


def _parse_report_id(report_id: str) -> FieldReportId | None:
    try:
        return FieldReportId(uuid.UUID(report_id))
    except ValueError:
        return None


def _store_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv mağazalar — `tenant_id` şərti İKİNCİ TƏCRİD QATIDIR (CLAUDE.md §6)."""
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows]


def _store_name(session: Session, store_id: Any) -> str:
    """Mağaza adı — `screen_data._store_name` ilə eyni qərar və eyni şərt."""
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s AND tenant_id = %s",
        (store_id, session.tenant_id),
    ).fetchone()
    return str(row["name"]) if row else f"#{str(store_id)[:8]}"


def _min_detail_length(session: Session) -> int:
    """ROOT parametri + SXEM DÖŞƏMƏSİ.

    `max(...)` domendəki ilə eyni ifadədir (`FieldReport.__init__`): Root
    `system_limits`-də 0 yazsa belə sxem `CHECK`-i sətri rədd edərdi və ekran
    istifadəçini anlaşılmaz DB xətasına aparardı.
    """
    key = SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH
    value = int(session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key])))
    return max(SCHEMA_MIN_DETAIL_LENGTH, value)


def _max_photos(session: Session) -> int:
    """ROOT parametri — ekranda hardcode ədəd YOXDUR."""
    key = SystemLimitKey.FIELD_REPORT_MAX_PHOTOS
    value = int(session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key])))
    return value if value > 0 else int(DEFAULT_LIMITS[key])


__all__ = [
    "LIST_RESTRICTED_NOTICE",
    "PENDING_PHOTO_PREFIX",
    "SCREEN_TEMPLATE_FAMILY",
    "FieldReportsController",
]
