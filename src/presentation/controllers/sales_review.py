"""«Şübhəli Satışlar» növbəsinin YAZI yolu — `SalesReviewQueueUseCase` (bölmə 6).

──────────────────────────────────────────────────────────────────────────────
AUDİT USE CASE-DƏDİR, BURADA TƏKRARLANMIR
──────────────────────────────────────────────────────────────────────────────
`reassign()` `SALES_MATCH_REASSIGNED`, `confirm()` isə `SALES_MATCH_CONFIRMED`
audit sətrini ÖZÜ yazır. Kontrollerdə ikinci bir audit çağırışı hər təyinatı
iki dəfə jurnalladar və "neçə təyinat oldu" sualına iki fərqli cavab verərdi.

──────────────────────────────────────────────────────────────────────────────
EKRAN ÇEK NÖMRƏSİ, USE CASE İSƏ ID İŞLƏDİR
──────────────────────────────────────────────────────────────────────────────
Ekran domen tiplərini tanımır (bax `controllers/__init__.py`) və sətri ÇEK
NÖMRƏSİ (`one_c_document_id`) ilə göstərir. Çek → `transaction_id` və ad →
`employee_id` xəritələri hər `refresh()`-də qurulur və kontrollerdə saxlanılır
— eyni naxış `fine_entry.py`-dədir. Xəritədə olmayan açar SÜKUTLA keçilmir:
istifadəçiyə "siyahı köhnəlib" deyilir və siyahı yenilənir, çünki səhv sətrə
təyinat REAL PULA (xal → mükafat) təsir edir.

──────────────────────────────────────────────────────────────────────────────
"TƏSDİQLƏ" İLƏ "TƏYİN ET" FƏRQLİDİR
──────────────────────────────────────────────────────────────────────────────
Seçilmiş işçi 1C-nin təklifi ilə EYNİDİRSƏ `confirm()` çağırılır: sətir
növbədən çıxır, xal TOXUNULMUR (o, artıq düzgün işçidədir). Fərqlidirsə
`reassign()` çağırılır və xal köçürülür. İkisini birləşdirsəydik, hər təsdiq
lazımsız bir xal köçürməsi yaradardı və `points_ledger`-də mənasız sətirlər
toplanardı.

──────────────────────────────────────────────────────────────────────────────
HƏR ƏMƏLİYYAT ÖZ SESSİYASINDA
──────────────────────────────────────────────────────────────────────────────
Növbə ekranı uzun müddət açıq qalır (operator sətir-sətir baxır); uzun-ömürlü
tranzaksiya `sales_transactions` sətirlərini kilidli saxlayar və sinxronizasiya
worker-ini bloklayardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_f import UnassignedSalesScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Toplu təyinatda audit sətrinə düşən səbəb. Use case minimum 5 simvol tələb
#: edir (`_clean_reason`) və səbəb SÜTUNU boş qala bilməz — "kim, nə vaxt,
#: NİYƏ" sualının üçüncü hissəsi mübahisədə ən çox soruşulanıdır.
BULK_REASON = "Şübhəli satış növbəsindən toplu təyinat"
SINGLE_REASON = "Şübhəli satış növbəsindən əl ilə təyinat"


class SalesReviewController:
    """«Şübhəli Satışlar» ekranını `SalesReviewQueueUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: çek nömrəsi → növbə sətri (`ReviewQueueItem`).
        self._items: dict[str, Any] = {}
        #: işçi adı → `EmployeeId`.
        self._employees: dict[str, Any] = {}

    # ------------------------------- seçimlər -------------------------------- #

    def employee_names(self) -> list[str]:
        """Ekran KONSTRUKTORU üçün işçi siyahısı (combo-box dəyərləri).

        Cərimə ekranındakı siyahıdan FƏRQLİDİR: orada operatorun ÖZ filialları
        süzülür (`FineEntryController.options`), burada isə satış istənilən
        filialdan gələ bilər və növbəyə baxan şəxs (`can_manage_sales_points`)
        şirkət miqyasındadır. Cərimə siyahısını təkrar işlətsəydik, admin
        boş açılan siyahı görər və heç bir sətri təyin edə bilməzdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                self._employees = _active_employee_names(session)
        except Exception:
            _error_log.exception("SALES_QUEUE_EMPLOYEES_FAILED")
            self._employees = {}
        return sorted(self._employees)

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: UnassignedSalesScreen) -> None:
        screen.rematch_requested.connect(lambda: self.refresh(screen))
        screen.assigned.connect(lambda receipt, name: self._on_assign(screen, receipt, name))
        screen.bulk_assign_requested.connect(lambda pairs: self._on_bulk(screen, pairs))
        self.refresh(screen)

    def refresh(self, screen: UnassignedSalesScreen) -> None:
        """Növbəni bazadan yenidən oxuyur.

        `[Yenidən Uyğunlaşdır]` düyməsi də buraya bağlanır: avtomatik
        uyğunlaşdırma sinxronizasiya worker-ində işləyir (`SalesMatcher`) və
        GUI-dən işə salınmır — düymənin verə biləcəyi yeganə DOĞRU nəticə
        worker-in bu vaxta qədər etdiklərini göstərməkdir. Onu "matcher-i
        işə sal" kimi qursaydıq, GUI prosesi minlərlə sətri emal edərdi və
        eyni iş iki yerdə paralel gedərdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                items = session.sales_review.queue(tenant_id=session.tenant_id, actor=self._actor)
                if not self._employees:
                    self._employees = _active_employee_names(session)
        except KompasOSError as error:
            screen.show_error(title="Növbə açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("SALES_QUEUE_LOAD_FAILED")
            screen.show_error(
                title="Növbə açıla bilmədi",
                message="Siyahı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        self._items = {item.one_c_document_id: item for item in items}
        total = sum(item.gross_amount.amount for item in items)
        # Açarlar ekranın FAKTİKİ oxuduqlarıdır: `receipt`, `date`, `amount`,
        # `suggestion`, `confidence` — maket yolundakı `preview_data.
        # UNASSIGNED_SALES` ilə EYNİ dəst (CLAUDE.md bölmə 6).
        screen.set_sales(
            [
                {
                    "receipt": item.one_c_document_id,
                    "date": f"{item.transaction_date:%d.%m %H:%M}",
                    "amount": f"{item.gross_amount.amount} ₼",
                    "suggestion": item.suggested_employee_name,
                    "confidence": str(_confidence_percent(item)),
                }
                for item in items
            ],
            total_amount=f"{total} ₼",
        )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_assign(self, screen: UnassignedSalesScreen, receipt: str, employee_name: str) -> None:
        self._apply(screen, [(receipt, employee_name)], reason=SINGLE_REASON)

    def _on_bulk(self, screen: UnassignedSalesScreen, pairs: Any) -> None:
        """`[Seçilmişləri Toplu Təyin Et]` — seçilməmiş sətirlər ekranda süzülüb."""
        cleaned = [
            (str(pair[0]), str(pair[1]))
            for pair in (pairs or [])
            if isinstance(pair, (list, tuple)) and len(pair) == 2  # noqa: PLR2004 — (çek, ad)
        ]
        if not cleaned:
            screen.show_error(
                title="Sətir seçilməyib",
                message="Toplu təyinat üçün ən azı bir sətirdə işçi seçin.",
            )
            self.refresh(screen)
            return
        self._apply(screen, cleaned, reason=BULK_REASON)

    def _apply(
        self, screen: UnassignedSalesScreen, pairs: list[tuple[str, str]], *, reason: str
    ) -> None:
        """Təyinatları BİR sessiyada icra edir.

        Toplu əməliyyat tək tranzaksiyadadır və bu, ümumi "hər əməliyyat öz
        sessiyasında" qaydasının İSTİSNASI DEYİL: istifadəçi üçün bu, BİR
        əməliyyatdır («Toplu Təyin Et»). Yarısı yazılıb yarısı yazılmayan
        toplu təyinat xal balanslarını izah edilə bilməyən vəziyyətdə
        qoyardı — hansı sətrin keçdiyini yalnız audit jurnalından tapmaq
        lazım gələrdi.
        """
        unknown = [receipt for receipt, _ in pairs if receipt not in self._items]
        if unknown:
            screen.show_error(
                title="Siyahı köhnəlib",
                message="Bəzi sətirlər artıq emal edilib. Siyahı yenilənir.",
            )
            self.refresh(screen)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                for receipt, employee_name in pairs:
                    self._resolve_one(session, receipt, employee_name, reason=reason)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Təyinat yazılmadı", message=error.user_message)
            self.refresh(screen)
            return
        except Exception:
            _error_log.exception("SALES_ASSIGN_FAILED")
            screen.show_error(
                title="Təyinat yazılmadı",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            self.refresh(screen)
            return

        self.refresh(screen)

    def _resolve_one(
        self, session: Session, receipt: str, employee_name: str, *, reason: str
    ) -> None:
        item = self._items[receipt]
        employee_id = self._employees.get(employee_name.strip())
        if employee_id is None:
            raise KompasOSError(
                f"Seçilmiş işçi tapılmadı: {employee_name}",
                user_message="Seçilmiş işçi siyahıda yoxdur. Siyahını yeniləyin.",
            )

        # Seçim 1C-nin təklifi ilə eynidirsə TƏSDİQdir, əks halda KÖÇÜRMƏ
        # (bax modul başlığı).
        if item.suggested_employee_id is not None and item.suggested_employee_id == employee_id:
            session.sales_review.confirm(
                tenant_id=session.tenant_id,
                actor=self._actor,
                transaction_id=item.transaction_id,
            )
            return

        session.sales_review.reassign(
            tenant_id=session.tenant_id,
            actor=self._actor,
            transaction_id=item.transaction_id,
            employee_id=employee_id,
            reason=reason,
        )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _confidence_percent(item: Any) -> int:
    """`MatchConfidence` → ekrandakı faiz.

    Domendə FAİZ YOXDUR — uyğunluq kateqoriyadır (`EXACT_MATCH`,
    `LOW_CONFIDENCE_MATCH`, `UNASSIGNED`). Ekran isə rəqəm gözləyir və
    50%-dən aşağını xəbərdarlıq tonunda göstərir. Ona görə burada YALNIZ
    həmin astananın İKİ tərəfi təmsil olunur: kateqoriyanı faizə çevirən
    bir düstur uydursaydıq, ekranda mövcud olmayan bir dəqiqlik göstərilərdi.
    """
    return 0 if item.is_unassigned else 60


def _active_employee_names(session: Any) -> dict[str, Any]:
    """Tenant üzrə AKTİV işçilər — `ad → id`.

    Adlar unikal olmaya bilər; eyni adlı ikinci işçi sözlükdə birincini
    ƏVƏZLƏYƏR. Bu, məlum məhdudiyyətdir və burada ad-a soyad-a əlavə olaraq
    heç nə göstərilmir, çünki ekranın açılan siyahısı yalnız MƏTN qəbul edir
    (`UnassignedSalesScreen(employees=[...])`).
    """
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
    return {f"{row['first_name']} {row['last_name']}".strip(): row["id"] for row in rows}


__all__ = ["BULK_REASON", "SINGLE_REASON", "SalesReviewController"]
