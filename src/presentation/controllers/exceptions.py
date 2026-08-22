""" "İstisnalar" ekranının yazı yolu — Vahid İstisna Motoru (#9, Faza 3/5).

kompasos11.md Faza 5, bənd 9: ekran HƏM oxuyur (açıq siyahı), HƏM yazır
(nəzərdən keçir / rədd et) — CLAUDE.md bölmə 6-ya görə belə ekranın ÖZ
kontrolleri olur, `screen_data.py`-a bağlanmır (`screen_data.py` YALNIZ oxu
yolunu bağlayır). Naxış `controllers/plugin_admin.py` və `controllers/
root_control.py`-dan götürülüb: `attach()` siqnalları bağlayır və ekranı ilk
dəfə DOLDURUR (`refresh`) — `app.py::_register_screens`-in maket/canlı
doldurma addımı bu ekran üçün İŞLƏMİR, çünki `ScreenDataBinder._binders()`-də
"exceptions" açarı YOXDUR (Qrup İ-dəki digər "maketsiz" Faza 5/6 ekranları —
İnfrastruktur, Plugin-lər, Panel Qurucusu — ilə EYNİ qərar).

──────────────────────────────────────────────────────────────────────────────
"NƏZƏRDƏN KEÇİRİLDİ" DİALOQSUZ, "RƏDD ET" DİALOQLU
──────────────────────────────────────────────────────────────────────────────
Domen qaydası budur (bax `ExceptionRecord.dismiss` / `.mark_reviewed`): rədd
qərarı İZAH TƏLƏB EDİR (siqnal SÖNDÜRÜLÜR — `dedupe_key` səbəbindən bir daha
yaranmayacaq), nəzərdən keçirmə isə YOX (arxasında adətən başqa bir izlənə
bilən əməliyyat — cərimə, söhbət, növbə dəyişikliyi — durur). Kontroller bu
fərqi TƏKRARLAMIR, sadəcə YANSIDIR: "Rədd Et" düyməsi səbəb dialoquna aparır
(`controllers/camera_queue.py::_ask_reason` ilə eyni naxış), "Nəzərdən
Keçirildi" isə birbaşa yazılır.

Doğrulamanın ÖZÜ domen qatındadır (`ExceptionRecord._close`) — kontroller
minimum qeyd uzunluğunu YENİDƏN yoxlamır. `system_limits.
EXCEPTION_REVIEW_NOTE_MIN_LENGTH` dəyişəndə burada heç nə düzəldilmir; domen
istisnası olduğu kimi (`error.user_message`) ekrana çatdırılır.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from src.domain.value_objects.identifiers import EmployeeId, ExceptionId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.exception_engine import ExceptionView
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_i import ExceptionsScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Ciddiyyət kodu → Azərbaycanca mətn. `.get(code, code)` naməlum dəyəri
#: GİZLƏTMİR — sxem yeni ciddiyyət əlavə etsə, ekran onu KODU İLƏ göstərir,
#: sükutla "Orta" kimi yanlış təsnif ETMİR (`ExceptionSeverity` sərt siyahıdır,
#: bax `exception_signals.py` başlığı, amma kontroller yenə DEFENSİV qalır).
_SEVERITY_TEXT: dict[str, str] = {
    "LOW": "Aşağı",
    "MEDIUM": "Orta",
    "HIGH": "Yüksək",
    "CRITICAL": "Kritik",
}


class ExceptionsController:
    """ "İstisnalar" ekranını `ExceptionEngineUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: ExceptionsScreen) -> None:
        """Siqnalları bağlayır və ekranı ilk dəfə doldurur."""
        screen.reviewed_requested.connect(
            lambda exception_id: self._on_reviewed(screen, exception_id)
        )
        screen.dismissed_requested.connect(
            lambda exception_id: self._on_dismissed(screen, exception_id)
        )
        self.refresh(screen)

    def refresh(self, screen: ExceptionsScreen) -> None:
        """Açıq istisnaları bazadan yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.exceptions.list_open(tenant_id=session.tenant_id, actor=self._actor)
                rows = [_to_row(session, view) for view in views]
        except KompasOSError as error:
            screen.show_error(title="İstisnalar açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("EXCEPTIONS_LIST_FAILED")
            screen.show_error(
                title="İstisnalar açıla bilmədi",
                message="Siyahı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        # KÖHNƏ YAZI-XƏTASI BANNERİ TƏMİZLƏNİR (QA-FULL FAZA 3): uğurlu oxuma
        # siyahının HAZIRKI vəziyyətinin düzgün olduğunu sübut edir — əvvəlki
        # uğursuz «Rədd Et»/«Nəzərdən Keçirildi» cəhdinin xəbərdarlığı artıq
        # doğru deyil (naxış `plugin_page.py::_show_content`).
        _clear_section_errors(screen)
        screen.set_exceptions(rows)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_reviewed(self, screen: ExceptionsScreen, exception_id: str) -> None:
        """`[Nəzərdən Keçirildi]` — qeyd KÖNÜLLÜDÜR, dialoq açılmır."""
        self._decide(
            screen,
            exception_id,
            note=None,
            dismiss=False,
            failure_title="Nəzərdən keçirmə yazılmadı",
        )

    def _on_dismissed(self, screen: ExceptionsScreen, exception_id: str) -> None:
        """`[Rədd Et]` — səbəb MƏCBURİDİR (bax modul başlığı)."""
        reason = self._ask_reason(screen)
        if reason is None:
            return
        self._decide(
            screen,
            exception_id,
            note=reason,
            dismiss=True,
            failure_title="Rədd əməliyyatı yazılmadı",
        )

    @staticmethod
    def _ask_reason(screen: ExceptionsScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            "İstisnanı rədd et",
            "Səbəb (məcburi) — audit jurnalına düşür və bu istisna bir daha yaranmayacaq:",
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None

    def _decide(
        self,
        screen: ExceptionsScreen,
        exception_id: str,
        *,
        note: str | None,
        dismiss: bool,
        failure_title: str,
    ) -> None:
        try:
            parsed_id = ExceptionId(uuid.UUID(exception_id))
        except ValueError:
            screen.show_error(title=failure_title, message="İstisna identifikatoru düzgün deyil.")
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                if dismiss:
                    session.exceptions.dismiss(
                        tenant_id=session.tenant_id,
                        actor=self._actor,
                        exception_id=parsed_id,
                        note=note or "",
                    )
                else:
                    session.exceptions.mark_reviewed(
                        tenant_id=session.tenant_id,
                        actor=self._actor,
                        exception_id=parsed_id,
                        note=note,
                    )
                session.commit()
        except KompasOSError as error:
            # `show_error()` BURADA İŞLƏDİLMİR (QA-FULL FAZA 3): qeyd domendə
            # RƏDD OLUNUB (məs. qısa səbəb), lakin QALAN AÇIQ istisnalar hələ
            # etibarlıdır. `show_error()` bütün siyahını xəta vəziyyəti ilə
            # əvəz edirdi — bu SƏTRİN rəddi ilə ƏLAQƏSİ olmayan digər açıq
            # istisnalar da görünməz olurdu (naxış `plugin_page.py::
            # _show_failure`, `drive_connection.py` başlığındakı eyni səhv).
            # SƏBƏB İSTİFADƏÇİYƏ ÇATIR: `set_section_error()` İŞLƏMİR, çünki o,
            # «{bölmə} yüklənə bilmədi» cümləsini qurur — YAZI rəddi üçün həm
            # yanlış cümlədir, həm də domenin dəqiq izahını («Rədd səbəbini
            # ətraflı yazın») ATIR. `_inform()` isə siyahını BOŞALTMADAN həmin
            # izahı göstərir (eyni naxış `fine_appeals.py`, `profile.py`).
            # SIRA VACİBDİR: əvvəl `refresh()` (siyahı dəyişməz qalır), sonra
            # izah — istifadəçi qərarını hansı sətrə verdiyini görür.
            _error_log.warning("EXCEPTION_DECISION_REJECTED", extra={"reason": error.user_message})
            self.refresh(screen)
            _inform(screen, failure_title, error.user_message)
            return
        except Exception:
            _error_log.exception("EXCEPTION_DECISION_FAILED", extra={"exception_id": exception_id})
            self.refresh(screen)
            _inform(screen, failure_title, "Əməliyyat yazılmadı. Yenidən cəhd edin.")
            return

        # Yazıdan SONRA siyahı yenidən oxunur — bağlanmış istisna artıq
        # "OPEN" siyahısında görünməməlidir (`list_open` yalnız açıqları
        # qaytarır), əks halda ekran YALAN danışardı.
        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — siyahını BOŞALTMADAN (naxış `fine_appeals.py::_inform`).

    `show_error()` bütün ekranı xəta vəziyyəti ilə əvəz edir; bir sətrin rəddi
    isə QALAN açıq istisnaları etibarsız etmir.
    """
    from PySide6.QtWidgets import QMessageBox, QWidget  # noqa: PLC0415

    # VALİDEYN YALNIZ HƏQİQİ WIDGET OLDUQDA (naxış `background_task.run_job`):
    # kontroller testləri ekran əvəzinə yüngül sahtə obyekt ötürür və
    # `QMessageBox(parent)` belə valideynlə `TypeError` atır — yəni səbəbi
    # GÖSTƏRMƏK cəhdi ikinci bir xətaya çevrilərdi.
    box = QMessageBox(screen if isinstance(screen, QWidget) else None)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


def _section_error(screen: Any, label: str) -> None:
    """`Screen.set_section_error` — YALNIZ metodu daşıyan ekranlarda.

    NİYƏ `getattr`, NİYƏ BİRBAŞA ÇAĞIRIŞ DEYİL (naxış `screen_data.
    report_section_error`): `_decide()` `screen: ExceptionsScreen` alsa da,
    duck-typing test saxtaları (məs. `tests/unit/test_exception_screen.py::
    _Screen`) `Screen` bazasından TÖRƏMİR və bu metodu daşımır. Birbaşa
    çağırış `AttributeError` atardı — xəbərdarlığı GÖRÜNƏN etmək cəhdi
    ikinci bir xətaya çevrilərdi.
    """
    reporter = getattr(screen, "set_section_error", None)
    if reporter is not None:
        reporter(label)


def _clear_section_errors(screen: Any) -> None:
    """`Screen.clear_section_errors` — eyni `getattr` ehtiyatı (bax `_section_error`)."""
    clearer = getattr(screen, "clear_section_errors", None)
    if clearer is not None:
        clearer()


def _to_row(session: Session, view: ExceptionView) -> dict[str, str]:
    """`ExceptionView` → ekranın FAKTİKİ gözlədiyi açarlar.

    Açarlar `preview_screens._exceptions`-dəki İLƏ EYNİDİR (CLAUDE.md bölmə
    6) — burada öz sözlüyümüzü qursaydıq, maket və canlı yol fərqli ad
    məkanlarına düşərdi (`menu.py` başlığındakı tarixi qüsur).
    """
    return {
        "id": str(view.exception_id),
        "source": view.source_code,
        "source_name": view.source_name_az,
        "employee": _employee_name(session, view.employee_id),
        "store": _store_name(session, view.store_id),
        "detail": view.detail,
        "severity": view.severity,
        "severity_text": _SEVERITY_TEXT.get(view.severity, view.severity),
        "date": view.created_at.astimezone().strftime("%d.%m.%Y %H:%M"),
    }


def _employee_name(session: Session, employee_id: str) -> str:
    """İşçi adı — tapılmazsa ID-nin qısa forması (`screen_data._employee_name` ilə eyni qərar)."""
    try:
        parsed = EmployeeId(uuid.UUID(employee_id))
    except ValueError:
        return f"#{employee_id[:8]}"
    employee = session.uow.employees.get(parsed)
    return str(employee.full_name) if employee is not None else f"#{employee_id[:8]}"


def _store_name(session: Session, store_id: str) -> str:
    """Mağaza adı — `tenant_id` şərti İKİNCİ TƏCRİD QATIDIR (CLAUDE.md bölmə 6)."""
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s AND tenant_id = %s",
        (store_id, session.tenant_id),
    ).fetchone()
    return str(row["name"]) if row else f"#{store_id[:8]}"


__all__ = ["ExceptionsController"]
