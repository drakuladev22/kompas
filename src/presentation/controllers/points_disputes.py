"""Xal etirazlarının MENECER yolu — «Satış Xalları» ekranının yazı tərəfi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`SalesPointsUseCase.decide_dispute()` yazılıb, testlidir və audit sətri də
qurur — LAKİN onu çağıran heç bir ekran yox idi. Nəticə: işçi xala etiraz
edir, etiraz `PENDING` qalır, 72 saatdan sonra `EXPIRED` olur və HEÇ KİMİN
siyahısına düşmür. Yəni hüquq verilib, ona çatan yol yoxdur — layihənin öz
qırmızı xətti («yazılıb, çağırılmır», bax `test_composition_optional_port_
wiring.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Bölmə həm OXUYUR, həm YAZIR və hər qərardan sonra siyahı YENİDƏN oxunmalıdır
— qərar verilmiş etiraz siyahıda qalsaydı, idarəçi onu ikinci dəfə açar və
«bu sətir artıq qərar alıb» xətası ilə qarşılaşardı. Bu dövrə `populate()`-ın
tək çağırışından uzun yaşayır, ona görə `screen_data.py` bağlaması yaramır.

──────────────────────────────────────────────────────────────────────────────
«GÖRMƏK = SƏLAHİYYƏTİN OLMASI» — QAPI BURADADIR
──────────────────────────────────────────────────────────────────────────────
Kontroller `can_manage_sales_points` OLMAYAN aktorda ekrana ÜMUMİYYƏTLƏ
qoşulmur (`attach` çağırılmır, bax `app.py`), yəni bölmə render OLUNMUR.
Bu, təhlükəsizlik qatı DEYİL — həqiqi qapı `decide_dispute()`-dakı
`_require`-dir; bura yalnız erqonomikadır (`kompasos-ui` bölmə 3).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yenisi açılır və commit edilir —
panel saatlarla açıq qala bilər (CLAUDE.md §6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.value_objects.identifiers import PointsEntryId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_f import SalesPointsScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Nişan mətnləri — ekran onları OLDUĞU KİMİ göstərir (bir mesajın iki mənbəyi
#: olmamalıdır, bax `set_disputes` docstring-i).
STATUS_PENDING: str = "Gözləyir"
STATUS_EXPIRED: str = "Vaxtı bitib"

#: Qərar səbəbinin minimum uzunluğu — DOMENDƏN gəlir, burada TƏKRAR YAZILMIR.
#: `PointsEntry.reject_dispute`/`reverse` eyni həddi tətbiq edir; dialoq onu
#: yalnız GÖSTƏRİR (naxış: `camera_queue._ask_reason`).


class PointsDisputeController:
    """Etiraz növbəsini `SalesPointsUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: SalesPointsScreen) -> None:
        screen.dispute_decided.connect(
            lambda entry_id, reject: self._on_decision(screen, entry_id, reject=bool(reject))
        )
        self.refresh(screen)

    # -------------------------------- oxu ------------------------------------ #

    def refresh(self, screen: SalesPointsScreen) -> None:
        """Qərar gözləyən etirazları yenidən oxuyur.

        UĞURSUZLUQ EKRANI XƏTA VƏZİYYƏTİNƏ SALMIR: bu bölmə səhifənin
        SONUNDADIR və yuxarıdakı balans/tarixçə kartları sağlamdır —
        `show_error()` onları da gizlədərdi (eyni qərar `root_control.py::
        _on_module_toggled`-dədir). Boş siyahı bölməni gizlədir, səbəb isə
        jurnala düşür.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                views = session.sales_points.list_undecided_disputes(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                rows = [_to_row(session, view) for view in views]
        except KompasOSError:
            _error_log.warning("POINTS_DISPUTE_LIST_DENIED", exc_info=True)
            screen.set_disputes([])
            return
        except Exception:
            _error_log.exception("POINTS_DISPUTE_LIST_FAILED")
            screen.set_disputes([])
            return

        screen.set_disputes(rows)

    # ------------------------------- yazı ------------------------------------ #

    def _on_decision(self, screen: SalesPointsScreen, entry_id: str, *, reject: bool) -> None:
        """`[Etirazı Rədd Et]` / `[Xalı Ləğv Et]` — SƏBƏB MƏCBURİDİR.

        İki düymə `decide_dispute()`-in İKİ qoluna gedir:
        `reject=True` sətri QÜVVƏDƏ saxlayır (etiraz haqlı deyil),
        `reject=False` isə `corrected_points=None` ilə xalı LƏĞV edir
        (`reverse()`). Qismən korreksiya bu bölmədə YOXDUR — o, məbləğ
        soruşan ayrıca formadır və buradakı sual «etiraz haqlıdırmı?»dır.

        SƏBƏB HƏR İKİ QOLDA TƏLƏB OLUNUR: işçiyə gedən bildiriş məhz həmin
        mətni daşıyır (`_safe_notify`), yəni boş səbəb «qərar verildi, niyəsi
        naməlum» deməkdir.
        """
        try:
            parsed_id = PointsEntryId(UUID(entry_id))
        except ValueError:  # pragma: no cover - siqnal ekrandan gəlir
            _error_log.warning("POINTS_DISPUTE_BAD_ID", extra={"entry_id": entry_id})
            return

        reason = self._ask_reason(screen, reject=reject)
        if reason is None:
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.sales_points.decide_dispute(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    entry_id=parsed_id,
                    reason=reason,
                    reject=reject,
                )
                session.commit()
        except KompasOSError as error:
            _inform(screen, "Qərar yazılmadı", error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("POINTS_DISPUTE_DECISION_FAILED", extra={"entry_id": entry_id})
            _inform(screen, "Qərar yazılmadı", "Dəyişiklik saxlanmadı. Yenidən cəhd edin.")
            return

        # Qərardan SONRA siyahı yenidən oxunur — sətir artıq qərar alıb və
        # siyahıda qalması yalan olardı.
        self.refresh(screen)

    @staticmethod
    def _ask_reason(screen: SalesPointsScreen, *, reject: bool) -> str | None:
        """Səbəb dialoqu — hədd DOMENDƏN oxunur, hərfi rəqəm yazılmır.

        Dövrə naxışı `camera_queue._ask_reason`-dandır (DEEP-GAP U9): qısa
        cavabda YAZILAN MƏTN İTMİR, dialoq `value=` ilə yenidən açılır.
        """
        from PySide6.QtWidgets import QInputDialog, QMessageBox  # noqa: PLC0415

        from src.domain.entities.shift import (  # noqa: PLC0415
            MIN_DECISION_REASON_LENGTH,
        )

        title = "Etirazı rədd et" if reject else "Xalı ləğv et"
        prompt = (
            "Qərarın səbəbi işçiyə bildiriş kimi gedir və audit jurnalına "
            f"düşür (minimum {MIN_DECISION_REASON_LENGTH} simvol):"
        )
        text = ""
        while True:
            text, accepted = QInputDialog.getMultiLineText(screen, title, prompt, text)
            if not accepted:
                return None
            cleaned = text.strip()
            if len(cleaned) >= MIN_DECISION_REASON_LENGTH:
                return cleaned
            box = QMessageBox(screen)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(title)
            box.setText(f"Səbəb ən azı {MIN_DECISION_REASON_LENGTH} simvol olmalıdır.")
            box.exec()


def _to_row(session: Session, view: Any) -> dict[str, str]:
    """`PointsDisputeView` → ekranın gözlədiyi açarlar.

    İŞÇİNİN ADI BURADA ƏLAVƏ OLUNUR: use case `EmployeeRepository`
    asılılığı GÖTÜRMÜR (bax `PointsDisputeView` başlığı), ekran isə «kimin
    etirazıdır?» sualının cavabını görməlidir. Ad tapılmasa BOŞ qalır —
    uydurma ad göstərmək yanlış rəqəm göstərməyin eynisidir.
    """
    employee = session.uow.employees.get(view.employee_id)
    sign = "+" if view.points >= 0 else ""
    return {
        "id": str(view.entry_id),
        "employee": str(getattr(employee, "full_name", "")) if employee is not None else "",
        "points": f"{sign}{view.points} xal",
        "reason": view.dispute_reason,
        "status": STATUS_EXPIRED if view.is_expired else STATUS_PENDING,
    }


def _inform(screen: Any, title: str, message: str) -> None:
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    QMessageBox.information(screen, title, message)


__all__ = ["STATUS_EXPIRED", "STATUS_PENDING", "PointsDisputeController"]
