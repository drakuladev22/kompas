"""Performans Qiymətləndirməsi YAZI yolu — #20, kompasos11.md Faza 8.

CLAUDE.md §6: bu ekran HƏM oxuyur (işçi dropdown-u, KPI kataloqu, keçmiş
dövrlər), HƏM yazır (`[Yadda Saxla]`) — ona görə ÖZ kontrolleri var,
`screen_data.py`-a bağlanmır (`controllers/exceptions.py`/`controllers/
open_shift.py` ilə eyni qərar).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.

──────────────────────────────────────────────────────────────────────────────
İŞÇİ DROPDOWN-U ARTIQ HİYERARXİYAYA GÖRƏ SÜZÜLÜR
──────────────────────────────────────────────────────────────────────────────
Dropdown-a YALNIZ aktorun CİDDİ ŞƏKİLDƏ yuxarıda olduğu işçilər düşür
(`_eligible_employees` — `positions.priority > aktorun priority-si`, kiçik
rəqəm = yüksək səlahiyyət). Bu, `PerformanceReviewUseCase.submit_review`-dəki
Strict Hierarchy Guard-ı TƏKRARLAMIR, sadəcə istifadəçi təcrübəsini
yaxşılaşdırır: seçim siyahısında olmayan adı seçib SONRA "icazəniz yoxdur"
mesajı almaqdansa, siyahının özü yalnız icazəli adları göstərir. Əsl qapı
YENƏ DƏ use case-dədir — bu, YALNIZ UI qısaldılması, təhlükəsizlik sərhədi
DEYİL (ekranı yan keçən çağırış use case-in ÖZ yoxlamasına tabedir).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from src.domain.value_objects.identifiers import EmployeeId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.performance_reviews import PerformanceReviewView
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.performance_review import PerformanceReviewScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class PerformanceReviewController:
    """ "Performans Qiymətləndirməsi" ekranını `PerformanceReviewUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma ---------------------------------- #

    def attach(self, screen: PerformanceReviewScreen) -> None:
        screen.employee_selected.connect(
            lambda employee_id: self._on_employee_selected(screen, employee_id)
        )
        screen.submit_requested.connect(lambda payload: self._on_submit(screen, payload))
        self.refresh(screen)

    def refresh(self, screen: PerformanceReviewScreen) -> None:
        """İşçi siyahısını, KPI kataloqunu və defolt dövrü yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                employees = _eligible_employees(session, self._actor)
                kpi_catalog = session.performance_reviews.kpi_catalog(session.tenant_id)
                default_period = session.performance_reviews.default_period(session.tenant_id)
        except KompasOSError as error:
            screen.show_error(title="Forma açılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("PERFORMANCE_REVIEW_FORM_LOAD_FAILED")
            screen.show_error(
                title="Forma açılmadı",
                message="İşçi siyahısı oxunmadı. Yenidən cəhd edin.",
            )
            return

        screen.set_kpi_catalog([(kpi.code, kpi.label_az) for kpi in kpi_catalog])
        screen.set_period(default_period)
        screen.set_employees(employees)
        screen.show_content()

    # ------------------------------ yazı yolu ---------------------------------- #

    def _on_employee_selected(self, screen: PerformanceReviewScreen, employee_id: str) -> None:
        """Dropdown dəyişdi — seçilmiş işçinin keçmiş dövrlərini göstərir."""
        try:
            parsed_id = EmployeeId(uuid.UUID(employee_id))
        except ValueError:
            screen.set_history([])
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.performance_reviews.list_for_employee(
                    tenant_id=session.tenant_id, actor=self._actor, employee_id=parsed_id
                )
        except KompasOSError:
            # Hiyerarxiya rədd etsə (nəzəri hal — dropdown artıq süzüb),
            # kart sadəcə boş qalır; forma özü hələ funksionaldır.
            screen.set_history([])
            return
        except Exception:
            _error_log.exception(
                "PERFORMANCE_REVIEW_HISTORY_FAILED", extra={"employee_id": employee_id}
            )
            screen.set_history([])
            return

        screen.set_history([_to_history_row(view) for view in views])

    def _on_submit(self, screen: PerformanceReviewScreen, payload: dict[str, Any]) -> None:
        """`[Yadda Saxla]` — yeni dövr YARADIR VƏ YA mövcudu YENİLƏYİR."""
        try:
            employee_id = EmployeeId(uuid.UUID(str(payload.get("employee_id", ""))))
        except ValueError:
            screen.show_form_error("İşçi identifikatoru düzgün deyil.")
            return

        period = str(payload.get("period", "")).strip()
        ratings = _clean_ratings(payload.get("ratings"))
        notes = str(payload.get("notes", "")).strip() or None

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.performance_reviews.submit_review(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee_id,
                    period=period,
                    ratings=ratings,
                    notes=notes,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_form_error(error.user_message)
            return
        except Exception:
            _error_log.exception(
                "PERFORMANCE_REVIEW_SUBMIT_FAILED", extra={"employee_id": str(employee_id)}
            )
            screen.show_form_error("Qiymətləndirmə yazılmadı. Yenidən cəhd edin.")
            return

        # Yazıdan SONRA tarixçə yenidən oxunur — YENİ/YENİLƏNMİŞ dövr dərhal
        # siyahıda görünməlidir (`controllers/open_shift.py` ilə eyni qayda).
        screen.show_form_error("")
        self._on_employee_selected(screen, str(employee_id))


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _clean_ratings(raw: Any) -> dict[str, int]:
    """Formadan gələn `{kod: currentData()}` sözlüyünü `dict[str, int]`-ə çevirir.

    `currentData()` Qt-də `Any` qaytarır (PySide tip sistemi runtime-da
    yoxlanmır) — burada açıq `int()` çevirməsi mypy-ə DEYİL, YARARSIZ dəyəri
    (`None`, sətir) sükutla kənarlaşdırmaq üçündür.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, int] = {}
    for code, value in raw.items():
        try:
            cleaned[str(code)] = int(value)
        except (TypeError, ValueError):
            continue
    return cleaned


def _to_history_row(view: PerformanceReviewView) -> dict[str, str]:
    """`PerformanceReviewView` → ekranların FAKTİKİ gözlədiyi açarlar.

    `group_g.ProfileScreen.set_performance_history` ilə EYNİ açar dəsti
    (CLAUDE.md §6) — `reviewer` sahəsi burada YOX, çünki ID-dən ada çevirmək
    əlavə sorğu tələb edir və composer ekranı onsuz da reviewer-i BİLİR
    (aktorun özüdür).
    """
    return {
        "period": view.period,
        "overall_score": str(view.overall_score) if view.overall_score is not None else "",
        "notes": view.notes or "",
    }


def _eligible_employees(session: Session, actor: Employee) -> list[tuple[str, str]]:
    """Aktorun CİDDİ ŞƏKİLDƏ yuxarıda olduğu, aktiv işçilər (modul başlığı)."""
    rows = session.uow.connection.execute(
        """
        SELECT e.id, e.first_name, e.last_name
          FROM employees e
          JOIN positions p ON p.id = e.position_id
         WHERE e.tenant_id = %s AND e.is_active AND p.priority > %s
         ORDER BY e.last_name, e.first_name
         LIMIT 500
        """,
        (session.tenant_id, actor.priority.value),
    ).fetchall()
    return [(str(row["id"]), f"{row['first_name']} {row['last_name']}".strip()) for row in rows]


__all__ = ["PerformanceReviewController"]
