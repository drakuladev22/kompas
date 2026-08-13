"""İşdən Çıxma Riski ekranının OXU yolu — #21, kompasos11.md Faza 9.

Bu ekran YALNIZ oxuyur (bax `screens/attrition_risk.py` başlığı), lakin ÖZ
kontrolleri var, `screen_data.py`-a BAĞLANMIR. Səbəb: baxış `AttritionRiskUseCase.
list_for_tenant`-də AUDİT-lənir (CLAUDE.md §5 — "audit istisna udmur") və
`can_view_attrition_risk` yoxlaması use case-in ÖZÜNDƏDİR. `screen_data.py`-ın
YALNIZ-OXU binder-ləri isə heç bir audit/icazə yoxlaması aparmır (onlar artıq
giriş etmiş adminin ÜMUMİ panelini doldururlar, bax `screen_data.py` başlığı).
Audit-lənən oxu ilə audit-lənməyən "canlı doldurucu" eyni koda qarışsaydı,
gələcək bir modul səhvən audit-siz oxu YAZARDI və "kim bu balları gördü?"
sualı cavabsız qalardı.

SESSİYA SAXLANILMIR: hər `refresh()` yeni sessiya açır və bağlayır
(CLAUDE.md §6 — kontroller sessiyanı SAXLAMIR).

──────────────────────────────────────────────────────────────────────────────
İŞÇİ/MAĞAZA ADI NİYƏ AYRI SORĞU İLƏ GƏLİR
──────────────────────────────────────────────────────────────────────────────
`AttritionRiskScoreView` (use case qatı) `employee_id`-dən başqa insan-oxunan
heç nə daşımır — bal HESABLAMASI adı BİLMƏMƏLİDİR (saf domen məntiqi). Ad/
mağaza BURADA, TƏK bir toplu sorğu ilə (`employee_id = ANY(...)`) əldə edilir
— `performance_review.py::_eligible_employees` ilə EYNİ naxış (kontroller
səviyyəsində birbaşa SQL, N+1 sorğu YOX).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.attrition_risk import AttritionRiskScoreView
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.identifiers import EmployeeId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.attrition_risk import AttritionRiskScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `domain.attrition_rules.AttritionSignal.SCORE_CAP`-ın öz sətir dəyəri —
#: burada TƏKRARLANIR ki, bu fayl domen modulunu idxal etməyə məcbur qalmasın
#: (yalnız görüntü qurur, hesablama etmir — `factors_json` artıq HAZIR gəlir).
_SCORE_CAP_SIGNAL = "SCORE_CAP"


class AttritionRiskController:
    """ "İşdən Çıxma Riski" ekranını `AttritionRiskUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma ---------------------------------- #

    def attach(self, screen: AttritionRiskScreen) -> None:
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: AttritionRiskScreen) -> None:
        """Siyahını yenidən oxuyur — hər çağırış AYRI, audit-lənən sessiyadır."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.attrition_risk.list_for_tenant(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                names = _employee_labels(session, [view.employee_id for view in views])
        except KompasOSError as error:
            screen.show_error(title="Siyahı açılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ATTRITION_RISK_LOAD_FAILED")
            screen.show_error(
                title="Siyahı açılmadı",
                message="İşdən çıxma riski balları oxunmadı. Yenidən cəhd edin.",
            )
            return

        screen.set_scores([_to_row(view, names) for view in views])


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee_labels(
    session: Session, employee_ids: list[EmployeeId]
) -> dict[EmployeeId, tuple[str, str]]:
    """`employee_id → (tam ad, mağaza adı)` — TƏK toplu sorğu."""
    if not employee_ids:
        return {}
    rows = session.uow.connection.execute(
        """
        SELECT e.id, e.first_name, e.last_name, COALESCE(s.name, '—') AS store_name
        FROM employees e
        LEFT JOIN stores s ON s.id = e.store_id
        WHERE e.tenant_id = %s AND e.id = ANY(%s)
        """,
        (session.tenant_id, list(employee_ids)),
    ).fetchall()
    return {
        row["id"]: (f"{row['first_name']} {row['last_name']}".strip(), row["store_name"])
        for row in rows
    }


def _to_row(
    view: AttritionRiskScoreView, names: dict[EmployeeId, tuple[str, str]]
) -> dict[str, str]:
    """`AttritionRiskScoreView` → `screens/attrition_risk.py::set_scores`-un gözlədiyi açarlar."""
    full_name, store_name = names.get(view.employee_id, (str(view.employee_id), "—"))
    factors_lines = [
        str(payload["izah"])
        for signal, payload in view.factors.items()
        if signal != _SCORE_CAP_SIGNAL and isinstance(payload, dict) and payload.get("izah")
    ]
    return {
        "employee": full_name,
        "store": store_name,
        "score": f"{view.score:.0f}",
        "band_text": "Yüksək risk" if view.is_high_risk else "Normal",
        "is_high_risk": "1" if view.is_high_risk else "0",
        "factors_text": " • ".join(factors_lines) or "—",
    }


__all__ = ["AttritionRiskController"]
