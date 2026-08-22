"""Aylıq Cərimə İcmalının YAZI yolu — bölmə 4 (miqrasiya 003).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Ekran HƏM oxuyur, HƏM yazır və hər yazıdan sonra siyahı YENİDƏN oxunmalıdır:
nəşr olunmuş cərimə `PENDING_REVIEW`-dan çıxır, yəni `list_pending_review`
onu artıq qaytarmır. Siyahı ekranda qalsaydı, istifadəçi eyni cəriməni ikinci
dəfə göndərməyə çalışar və "nəşr gözləyən cərimə yoxdur" istisnası ilə
qarşılaşardı. Bu dövrə `populate()`-ın tək çağırışından uzun yaşayır, ona görə
`screen_data.py` bağlaması yararsızdır.

──────────────────────────────────────────────────────────────────────────────
NƏŞR TƏK TRANZAKSİYADIR — VƏ YAZMA MƏHZ BURADADIR
──────────────────────────────────────────────────────────────────────────────
`MonthlyFineReviewUseCase` repository ALMIR: `publish_batch` cərimələri
yaddaşda (`dict[FineId, Fine]`) mutasiya edir, sətirlərə yazmaq isə çağıranın
işidir. Ona görə burada üç addım BİR sessiyada gedir:

    oxu (`list_pending_review`) → `publish_batch(...)` → `save(...)` + commit

"Bir anda görünür" tələbi TEXNİKİ tələbdir (use case başlığı): qismən nəşr
bəzi işçilərə cəriməni digərlərindən əvvəl göstərərdi. Bir istisna bütün
dəsti geri qaytarır və ekrana HEÇ NƏ dərc olunmadığı açıq yazılır — "qismən
uğur" illüziyası ən pis nəticədir, çünki istifadəçi qalanını əl ilə axtarardı.

Audit sətri də EYNİ tranzaksiyadadır (`uow.audit`), yəni rollback halında nə
cərimə, nə də audit qeydi qalır.

SESSİYA SAXLANILMIR: hər əməliyyat üçün yenisi açılır. İcmal paneli ayın
əvvəlində saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu müddət boyu
`fines` sətirlərində kilid saxlayar və kamera operatorlarının yeni cərimə
yazmasını bloklayardı.

──────────────────────────────────────────────────────────────────────────────
QƏRAR ETİKETLƏRİ ENUM-DAN GƏLİR
──────────────────────────────────────────────────────────────────────────────
`decision_options()` siyahını `ReviewDecision` üzvləri üzərində qurur — ekran
onları UYDURMUR (bax `screens/fine_review.py` başlığı). Enum-a yeni üzv əlavə
olunsa, siyahı özü genişlənir; etiketi yazılmamış üzv öz KODU ilə görünür,
gizlənmir — sükutla itmiş qərar variantı ən çətin tapılan qüsurdur.

──────────────────────────────────────────────────────────────────────────────
SƏBƏB DİALOQU BURADADIR
──────────────────────────────────────────────────────────────────────────────
"Sil" üçün səbəb domendə MƏCBURİDİR (`MIN_DISCARD_REASON_LENGTH`). Səbəb
`QInputDialog` ilə soruşulur (`annual_leave`/`camera_queue` naxışı) və qısa
cavab yazı yoluna ÜMUMİYYƏTLƏ girmir: use case onu onsuz da rədd edərdi,
lakin o vaxta qədər istifadəçi bütün dəsti göndərməyə çalışmış olardı.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.application.use_cases.fine_review import (
    MIN_DISCARD_REASON_LENGTH,
    FineDecision,
    ReviewDecision,
)
from src.presentation.controllers.screen_data import _MONTHS_AZ
from src.presentation.screens.fine_review import (
    FineReviewGroup,
    FineReviewRow,
    PublishSummary,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.entities.employee import Employee
    from src.domain.entities.fine import Fine
    from src.domain.value_objects.identifiers import FineId
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.fine_review import MonthlyFineReviewScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Siyahı oxuna bilmədikdə göstərilən mətn — ekran boş qalır, çökmür.
LIST_READ_FAILED = "Cərimə icmalı oxuna bilmədi. Yenidən cəhd edin."

#: Nəşr uğursuz olduqda: "heç biri" sözü QƏSDƏNDİR (bax modul başlığı).
PUBLISH_FAILED = "Cərimələr göndərilmədi — HEÇ BİRİ dərc olunmadı. Yenidən cəhd edin."

#: Naməlum qərar kodu — siqnal ekranın köhnə vəziyyətindən gələ bilər.
UNKNOWN_DECISION = "Qərar variantı tanınmadı."

#: Göndəriləcək sətir yoxdur (use case də eyni halda istisna atır).
EMPTY_BATCH = "Bu dövr üçün göndəriləcək cərimə yoxdur."

#: Ekrandakı siyahı ilə bazadakı dəst uyğun gəlmir (bax `_on_publish`).
LIST_CHANGED = (
    "Siyahı bu arada dəyişib — HEÇ NƏ göndərilmədi. Cərimələr yenidən oxundu, "
    "qərarlarınızı yoxlayıb təkrar göndərin."
)

#: Səbəb dialoqunun mətni. Minimum uzunluq DOMENDƏN gəlir, burada təkrar
#: YAZILMIR — ikisi ayrılsaydı, ekran qəbul etdiyi mətni use case rədd edərdi.
DISCARD_PROMPT = (
    f"Cərimənin silinmə səbəbi (məcburi, ən azı {MIN_DISCARD_REASON_LENGTH} simvol) — "
    "audit jurnalına olduğu kimi düşür:"
)

#: Çox qısa səbəb: yazı yoluna girmir, istifadəçi səbəbi AÇIQ öyrənir.
SHORT_REASON = f"Səbəb ən azı {MIN_DISCARD_REASON_LENGTH} simvol olmalıdır."

#: `ReviewDecision` → ekran etiketi. Mətnlər use case başlığındakı axının
#: özündəndir ("Saxla" (defolt) / "Sil"), yenidən adlandırılmır.
_DECISION_LABELS: dict[ReviewDecision, str] = {
    ReviewDecision.KEEP: "Saxla",
    ReviewDecision.DISCARD: "Sil",
}


def decision_options() -> list[dict[str, str]]:
    """Sətir qərarlarının variantları — SIRA `ReviewDecision`-dandır.

    Birinci üzv (`KEEP`) DEFOLTDUR və ekran da onu belə qəbul edir: use case
    qərarı verilməmiş sətri "Saxla" sayır (`publish_batch` docstring-i).
    """
    return [
        {"code": decision.value, "label": _DECISION_LABELS.get(decision, decision.value)}
        for decision in ReviewDecision
    ]


class MonthlyFineReviewController:
    """«Aylıq Cərimə İcmalı» ekranını `MonthlyFineReviewUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: Hazırda göstərilən dövr (`YYYY-MM`) — nəşr də ona aiddir.
        self._period = ""
        #: `fine_id → məbləğ` (SON oxunuşdan): təsdiq modalındakı cəmi
        #: mətn sətirlərindən deyil, `Decimal`-dan hesablayırıq.
        self._amounts: dict[str, Decimal] = {}
        #: `fine_id → filial açarı` — toplu qərar və filial sayı üçün.
        self._store_of: dict[str, str] = {}

    # -------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: MonthlyFineReviewScreen) -> None:
        # Variantlar SƏTİRLƏRDƏN ƏVVƏL verilir: sətir düymələri məhz bu
        # siyahıdan qurulur (bax `screens/fine_review.py::set_decision_options`).
        screen.set_decision_options(decision_options())
        screen.period_selected.connect(lambda period: self.refresh(screen, period=period))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        screen.decision_requested.connect(
            lambda fine_id, code: self._on_decision(screen, fine_id, code)
        )
        screen.group_decision_requested.connect(
            lambda store_key, code: self._on_group_decision(screen, store_key, code)
        )
        screen.publish_requested.connect(lambda payload: self._on_publish(screen, payload))
        self.refresh(screen)

    # -------------------------------- oxu yolu -------------------------------- #

    def refresh(
        self, screen: MonthlyFineReviewScreen, *, period: str = "", notice: str = ""
    ) -> None:
        """Seçilmiş dövrün nəşr gözləyən cərimələrini yenidən oxuyur.

        `period` boşdursa DEFOLT DÖVR seçilir: nəşr gözləyən ƏN KÖHNƏ ay.
        Səbəb — gecikmiş nəşr işçinin etiraz pəncərəsini də gecikdirir, ona
        görə ekran açılan kimi ən qədim borcu göstərməlidir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                periods = [
                    str(value)
                    for value in session.uow.fines.pending_review_periods(session.tenant_id)
                ]
                selected = _choose_period(periods, requested=period or self._period)
                fines = _read_fines(session, selected)
                groups, summary = self._build_groups(session, fines)
        except KompasOSError as error:
            screen.set_groups([])
            screen.show_form_error(error.user_message)
            return
        except Exception:
            _error_log.exception("FINE_REVIEW_LIST_FAILED", extra={"period": period})
            screen.set_groups([])
            screen.show_form_error(LIST_READ_FAILED)
            return

        self._period = selected
        screen.set_periods(_period_options(periods), selected=selected)
        screen.set_groups(groups, summary_text=summary)
        screen.show_notice(notice)

    def _build_groups(
        self, session: Session, fines: list[Fine]
    ) -> tuple[list[FineReviewGroup], str]:
        """Cərimələri filiallara görə qruplaşdırır və xülasə sətrini qurur."""
        self._amounts = {str(fine.id): fine.amount.amount for fine in fines}
        self._store_of = {str(fine.id): str(fine.store_id) for fine in fines}

        names = _display_names(session, fines)
        unsynced = _unsynced_camera_evidence(session, fines)
        groups = _group_rows(fines, names, unsynced)
        total = sum((fine.amount.amount for fine in fines), Decimal("0"))
        summary = (
            f"{len(fines)} cərimə · {len(groups)} filial · {_amount_text(total)} nəşr gözləyir"
            if fines
            else ""
        )
        return groups, summary

    # ------------------------------- sətir qərarı ----------------------------- #

    def _on_decision(self, screen: MonthlyFineReviewScreen, fine_id: str, code: str) -> None:
        decision = _parse_decision(code)
        if decision is None:
            screen.show_form_error(UNKNOWN_DECISION)
            return
        if decision is ReviewDecision.DISCARD:
            reason = self._ask_reason(screen)
            if reason is None:
                return
            screen.set_decision(fine_id, decision=decision.value, reason=reason)
            return
        screen.set_decision(fine_id, decision=decision.value, reason="")

    def _on_group_decision(
        self, screen: MonthlyFineReviewScreen, store_key: str, code: str
    ) -> None:
        """Bir filialın BÜTÜN sətirlərinə eyni qərar.

        Səbəb BİR DƏFƏ soruşulur və hamısına eyni mətn yazılır: 21 filial ×
        onlarla cərimə üçün sətir-sətir səbəb yazmaq praktikada mümkün deyil,
        toplu qərarın səbəbi isə onsuz da eynidir ("kamera nasazlığı", "səhv
        dövr"). Fərqli səbəb lazımdırsa sətir düyməsi yerində qalır.
        """
        decision = _parse_decision(code)
        if decision is None:
            screen.show_form_error(UNKNOWN_DECISION)
            return

        fine_ids = [fine_id for fine_id, store in self._store_of.items() if store == store_key]
        if not fine_ids:
            # Siyahı bu arada yenidən oxunmuş ola bilər — sükutla keçmirik,
            # çünki istifadəçi düyməni basıb və nəticə gözləyir.
            screen.show_form_error("Bu filialın sətirləri artıq siyahıda deyil.")
            return

        reason = ""
        if decision is ReviewDecision.DISCARD:
            asked = self._ask_reason(screen)
            if asked is None:
                return
            reason = asked

        for fine_id in fine_ids:
            screen.set_decision(fine_id, decision=decision.value, reason=reason)

    def _ask_reason(self, screen: MonthlyFineReviewScreen) -> str | None:
        """Səbəb dialoqu — boş/qısa cavab yazı yoluna GİRMİR."""
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(screen, "Cəriməni sil", DISCARD_PROMPT)
        if not accepted:
            return None
        # KÖHNƏ NÜSXƏ ƏVƏZLƏNDİ (`domain` sahibinin tapıntısı, `src/shared/
        # text.py`): `use_cases/fine_review.py` artıq `normalise_decision_
        # text` işlədir (Cf/görünməz simvolları atır) — bax `shift_swaps.py::
        # _ask_reason` şərhi. Nüsxə buradan da eyni mənbəyə keçirilir.
        cleaned = normalise_decision_text(text)
        if len(cleaned) < MIN_DISCARD_REASON_LENGTH:
            screen.show_form_error(SHORT_REASON)
            return None
        screen.show_form_error("")
        return cleaned

    # -------------------------------- yazı yolu ------------------------------- #

    def _on_publish(self, screen: MonthlyFineReviewScreen, payload: Any) -> None:
        """TƏK «[Bütün Filiallara Göndər]» düyməsi — bir tranzaksiya."""
        decisions = _validated_decisions(screen, payload)
        if decisions is None:
            return

        # TƏSDİQ MODALI MƏCBURİDİR: nəşr geri qaytarıla bilmir (bax
        # `screens/fine_review.py` başlığı). İmtina halında HEÇ NƏ baş vermir
        # — sessiya belə açılmır.
        if not self._confirm(screen, self._summary_for(decisions)):
            return

        published = 0
        discarded = 0
        try:
            with self._context.session(user_id=self._actor.id) as session:
                # SİYAHI YAZI ANINDA YENİDƏN OXUNUR — və dəst MÜQAYİSƏ EDİLİR.
                #
                # Ekrandakı nüsxə bir neçə dəqiqə köhnə ola bilər: bu arada
                # başqa admin nəşr edə, yaxud kamera operatoru YENİ cərimə
                # yaza bilər. İkinci hal təhlükəlidir — `publish_batch` `fines`
                # sözlüyündəki BÜTÜN `PENDING_REVIEW` sətirləri nəşr edir
                # (qərarı verilməmiş sətir "Saxla" sayılır), yəni istifadəçinin
                # HEÇ VAXT GÖRMƏDİYİ cərimə də açılardı. Ona görə uyğunsuzluq
                # halında heç nə yazılmır: sessiya commit-siz bağlanır və
                # istifadəçi təzə siyahı görür.
                fines = {fine.id: fine for fine in _read_fines(session, self._period)}
                if set(fines) != {decision.fine_id for decision in decisions}:
                    stale = True
                else:
                    stale = False
                    result = session.fine_review.publish_batch(
                        actor=self._actor,
                        tenant_id=session.tenant_id,
                        review_month=self._period,
                        fines=fines,
                        decisions=decisions,
                    )
                    # YALNIZ toxunulmuş sətirlər yazılır: qərar tətbiq
                    # olunmamış cəriməni yenidən yazmaq eyni dəyərləri geri
                    # yazardı, lakin hər sətir üçün bir UPDATE deməkdir.
                    for fine_id in [*result.published, *result.discarded]:
                        session.uow.fines.save(fines[fine_id])
                    session.commit()
                    published, discarded = len(result.published), len(result.discarded)
        except KompasOSError as error:
            # Səlahiyyət yoxluğu, boş dəst və səbəbsiz "Sil" bura düşür.
            # Mesaj domendəndir — xam istisna mətni (`str(error)`) daxili
            # kontekst daşıyır və ekrana çıxmır.
            self._fail(screen, error.user_message)
            return
        except Exception:
            _error_log.exception("FINE_PUBLISH_FAILED", extra={"period": self._period})
            self._fail(screen, PUBLISH_FAILED)
            return

        if stale:
            self._fail(screen, LIST_CHANGED)
            return

        # Yazıdan SONRA siyahı yenidən oxunur: nəşr olunanlar `PENDING_REVIEW`
        # -dan çıxdığı üçün icmaldan da çıxır.
        self.refresh(
            screen,
            notice=(
                f"{published} cərimə bütün filiallara göndərildi"
                + (f", {discarded} cərimə silindi" if discarded else "")
                + "."
            ),
        )

    def _fail(self, screen: MonthlyFineReviewScreen, message: str) -> None:
        """Siyahını yenidən oxuyur, SONRA səbəbi yazır.

        SIRA VACİBDİR: `set_groups` xəta sətrini təmizləyir (təzə siyahı köhnə
        xətanı daşımamalıdır), yəni əvvəl mesaj yazsaydıq o, yenidən oxumada
        sükutla silinərdi və istifadəçi səbəbsiz dəyişiklik görərdi.
        """
        self.refresh(screen)
        screen.show_form_error(message)

    def _summary_for(self, decisions: list[FineDecision]) -> PublishSummary:
        """Təsdiq modalının rəqəmləri — SON oxunuşun məbləğlərindən.

        Məbləğ `Decimal` üzərində toplanır: ekrandakı mətnləri ("25 ₼") geri
        çevirmək formatdan asılı olardı və format dəyişəndə cəm sükutla
        yanlış olardı.

        Mənbə `FineDecision` siyahısıdır, xam ekran yükü YOX: modalda
        göstərilən rəqəm use case-ə GEDƏCƏK dəstin eynisi olmalıdır — iki
        ayrı hesablama yolu bir-birindən yayına bilərdi.
        """
        keep = [
            str(decision.fine_id)
            for decision in decisions
            if decision.decision is not ReviewDecision.DISCARD
        ]
        discarded = len(decisions) - len(keep)
        total = sum((self._amounts.get(fine_id, Decimal("0")) for fine_id in keep), Decimal("0"))
        stores = {self._store_of.get(fine_id, "") for fine_id in keep}
        return PublishSummary(
            period_text=_period_label(self._period),
            publish_count=len(keep),
            discard_count=discarded,
            store_count=len(stores),
            amount_text=_amount_text(total),
        )

    def _confirm(self, screen: MonthlyFineReviewScreen, summary: PublishSummary) -> bool:
        """Təsdiq modalını açır — YALNIZ «Göndər» `True` qaytarır.

        Ayrı metoddur ki, testlər onu əvəz edə bilsin: modal `exec()` hadisə
        dövrəsini bloklayır və nəşr axınının qalan hissəsi Qt olmadan da
        yoxlanıla bilməlidir (`backup_admin`-dəki dialoq naxışının eynisi).
        """
        from PySide6.QtWidgets import QDialog  # noqa: PLC0415

        from src.presentation.screens.fine_review import (  # noqa: PLC0415
            PublishConfirmDialog,
        )

        dialog = PublishConfirmDialog(screen.theme, summary=summary, parent=screen)
        return bool(dialog.exec() == QDialog.DialogCode.Accepted)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _parse_decision(code: str) -> ReviewDecision | None:
    try:
        return ReviewDecision(code)
    except ValueError:
        return None


def _validated_decisions(
    screen: MonthlyFineReviewScreen, payload: Any
) -> list[FineDecision] | None:
    """Ekran yükünü yoxlayır və `FineDecision` siyahısına çevirir.

    `None` = axın DAYANIR (səbəb ekranda yazılıb). Ayrıca funksiyadır ki,
    `_on_publish` yalnız TRANZAKSİYA məntiqini saxlasın: doğrulama ilə yazma
    bir metoda yığıldıqda hansı şərtin nəşri dayandırdığı gözdən qaçırdı.
    """
    if not isinstance(payload, list):  # pragma: no cover - tip qoruyucusu
        return None
    decisions = _to_decisions([row for row in payload if isinstance(row, dict)])
    if decisions is None:
        screen.show_form_error(UNKNOWN_DECISION)
        return None
    if not decisions:
        # Boş dəst use case-də istisna atardı; burada dayandırmaq istifadəçiyə
        # eyni cavabı modal açmadan verir.
        screen.show_form_error(EMPTY_BATCH)
        return None
    return decisions


def _to_decisions(rows: list[dict[str, Any]]) -> list[FineDecision] | None:
    """Ekran yükü → `FineDecision` siyahısı. Naməlum kod → `None` (dayan).

    `fine_id` MƏTNDƏN `FineId`-ə çevrilir: ekran domen tiplərini tanımır və
    çevirmə sərhədi məhz buradadır. Yararsız identifikator bütün dəsti
    dayandırır — bir sətri sükutla atmaq istifadəçinin verdiyi qərarı
    itirərdi.
    """
    from uuid import UUID  # noqa: PLC0415

    from src.domain.value_objects.identifiers import FineId  # noqa: PLC0415

    decisions: list[FineDecision] = []
    for row in rows:
        decision = _parse_decision(str(row.get("decision", "")))
        if decision is None:
            return None
        try:
            fine_id = FineId(UUID(str(row.get("fine_id", ""))))
        except ValueError:
            return None
        reason = str(row.get("reason", "")) or None
        decisions.append(FineDecision(fine_id=fine_id, decision=decision, reason=reason))
    return decisions


def _read_fines(session: Session, period: str) -> list[Fine]:
    """Dövrün nəşr gözləyən cərimələri — dövr yararsızdırsa BOŞ siyahı."""
    parsed = _parse_period(period)
    if parsed is None:
        return []
    year, month = parsed
    fines: list[Fine] = session.uow.fines.list_pending_review(
        session.tenant_id, year=year, month=month
    )
    return fines


def _parse_period(period: str) -> tuple[int, int] | None:
    """`YYYY-MM` → `(il, ay)`. Yararsız dəyər `None` (use case də rədd edərdi)."""
    parts = period.split("-")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():  # noqa: PLR2004
        return None
    year, month = int(parts[0]), int(parts[1])
    if not 1 <= month <= 12:  # noqa: PLR2004 - ay aralığı
        return None
    return year, month


def _choose_period(periods: list[str], *, requested: str) -> str:
    """Göstəriləcək dövr: istənilən → mövcuddursa o, əks halda ƏN KÖHNƏ.

    Siyahı artan sıradadır (`pending_review_periods`), ona görə birinci
    element ən köhnə dövrdür.
    """
    if requested and requested in periods:
        return requested
    if periods:
        return periods[0]
    # Gözləyən dövr yoxdursa istənilən dəyər qalır: ekran boş vəziyyət
    # göstərəcək, lakin seçici son seçimi itirməyəcək.
    return requested


def _period_options(periods: list[str]) -> list[dict[str, str]]:
    return [{"key": period, "label": _period_label(period)} for period in periods]


def _period_label(period: str) -> str:
    """`2026-08` → «Avqust 2026». Aylar `screen_data`-dan gəlir.

    Ay adları BURADA TƏKRAR YAZILMIR: `strftime("%B")` sistem lokalından
    asılıdır və Windows-da ingiliscə qaytarır, halbuki interfeys dili yalnız
    Azərbaycan dilidir (bölmə 9).
    """
    parsed = _parse_period(period)
    if parsed is None:
        return period
    year, month = parsed
    return f"{_MONTHS_AZ[month - 1]} {year}"


def _amount_text(value: Decimal) -> str:
    """`Decimal("25.00")` → "25 ₼", `Decimal("25.50")` → "25.50 ₼".

    Mənasız sıfırlar kəsilir (`controllers/annual_leave.py::_day_number` ilə
    eyni qərar), lakin kəsr hissə ATILMIR: cərimə məbləği `NUMERIC(10,2)`-dir
    və qəpik real puldur.
    """
    if value == value.to_integral_value():
        return f"{value.to_integral_value()} ₼"
    return f"{value} ₼"


def _display_names(session: Session, fines: list[Fine]) -> dict[str, dict[str, str]]:
    """Ekran üçün ad xəritələri: işçilər, filiallar, cərimə növləri.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ USE CASE DEYİL, BİRBAŞA SQL
    ──────────────────────────────────────────────────────────────────────────
    `screen_data._fines` ilə eyni əsaslandırma: burada heç bir iş qərarı
    verilmir — nə status keçidi, nə hesablama, nə səlahiyyət yoxlaması.
    Yalnız identifikatorlar oxunaqlı ada çevrilir.

    OPERATOR ADI DA İŞÇİ CƏDVƏLİNDƏNDİR (`issued_by`), ona görə hər iki
    identifikator dəsti BİR sorğuda oxunur — sətir sayına görə sorğu açmaq
    (N+1) 21 filialın icmalında yüzlərlə gediş-gəliş demək olardı.
    """
    employee_ids = {fine.employee_id for fine in fines}
    employee_ids |= {fine.issued_by for fine in fines if fine.issued_by is not None}
    store_ids = {fine.store_id for fine in fines}
    type_ids = {fine.fine_type_id for fine in fines if fine.fine_type_id is not None}

    return {
        "employees": _lookup(
            session,
            "SELECT id, first_name, last_name FROM employees WHERE tenant_id = %s AND id = ANY(%s)",
            list(employee_ids),
            lambda row: f"{row['first_name'] or ''} {row['last_name'] or ''}".strip(),
        ),
        "stores": _lookup(
            session,
            "SELECT id, name FROM stores WHERE tenant_id = %s AND id = ANY(%s)",
            list(store_ids),
            lambda row: str(row["name"]),
        ),
        "fine_types": _lookup(
            session,
            "SELECT id, name_az FROM fine_types WHERE tenant_id = %s AND id = ANY(%s)",
            list(type_ids),
            lambda row: str(row["name_az"]),
        ),
    }


def _lookup(
    session: Session,
    sql: str,
    ids: list[Any],
    to_name: Callable[[Any], str],
) -> dict[str, str]:
    """`id → ad` xəritəsi. Boş identifikator dəsti üçün sorğu AÇILMIR."""
    if not ids:
        return {}
    rows = session.uow.connection.execute(sql, (session.tenant_id, ids)).fetchall()
    return {str(row["id"]): to_name(row) for row in rows}


def _unsynced_camera_evidence(session: Session, fines: list[Fine]) -> set[FineId]:
    """MANUAL_CAMERA cərimələrindən şəkli hələ Drive-a YÜKLƏNMƏYƏNLƏR (T3).

    ──────────────────────────────────────────────────────────────────────────
    `has_evidence` ƏVVƏL HƏMİŞƏ `True` İDİ
    ──────────────────────────────────────────────────────────────────────────
    `bool(fine.photo_evidence_url)` MANUAL_CAMERA axınında YANLIŞ mənbədir:
    həmin sütun sübutun DİSKƏ yazıldığı andaca (yəni növbə açarı kimi) dolur
    (bax `fine_entry.py::_issue` — "SIRA: ƏVVƏLCƏ ŞƏKİL DİSKƏ" bölməsi),
    Drive-a HƏQİQƏTƏN yüklənib-yüklənmədiyini demir. Nəticədə operator kartda
    "sübut var" görürdü, halbuki şəkil hələ lokal növbədə gözləyirdi.

    MƏNBƏ SÜZGƏCİ (`MANUAL_CAMERA`) BURADADIR, `unsynced_evidence_ids`-DƏ YOX
    — sorğu YALNIZ id dəsti oxuyur (`repositories.py`), "hansı mənbənin sübutu
    MƏCBURİDİR" isə biznes qaydasıdır və `_to_row`-un yanında qalmalıdır (bax
    `MonthlyFineReviewUseCase._unsynced_evidence`-in EYNİ qərarı — qayda İKİ
    yerdə YAŞAMIR, sadəcə İKİ yerdə İSTİFADƏ olunur).

    Boş `camera_ids` üçün sorğu AÇILMIR (`_lookup`-un eyni qaydası).
    """
    from src.domain.entities.fine import FineSource  # noqa: PLC0415

    camera_ids = [fine.id for fine in fines if fine.source is FineSource.MANUAL_CAMERA]
    if not camera_ids:
        return set()
    # `uow.fines` `Any` qaytarır (`connection.py::UnitOfWork.fines`) — yerli
    # tipli dəyişən mypy-ın `--warn-return-any` xəbərdarlığını qapadır, açıq
    # `cast()`-dən fərqli olaraq NƏTİCƏNİN ÖZÜNÜ dəyişmir.
    result: set[FineId] = session.uow.fines.unsynced_evidence_ids(camera_ids)
    return result


def _group_rows(
    fines: list[Fine], names: dict[str, dict[str, str]], unsynced: set[FineId]
) -> list[FineReviewGroup]:
    """Cərimələri filiala görə qruplaşdırır; qruplar filial ADINA görə sıralanır.

    Sətirlərin öz sırası SQL-dən gəlir (`fine_date`), burada dəyişdirilmir:
    tarix sırası icmalın oxunuş ritmidir.

    Adı tapılmayan filial/işçi GİZLƏDİLMİR — identifikatorun qısa forması
    göstərilir (`controllers/annual_leave.py::_employee_name` ilə eyni qərar):
    ad oxuna bilməsə də cərimə real pul kəsintisidir və qərar gözləyir.
    """
    buckets: dict[str, list[FineReviewRow]] = {}
    totals: dict[str, Decimal] = {}
    labels: dict[str, str] = {}

    for fine in fines:
        store_key = str(fine.store_id)
        labels[store_key] = names["stores"].get(store_key) or _short(store_key)
        buckets.setdefault(store_key, []).append(_to_row(fine, names, unsynced))
        totals[store_key] = totals.get(store_key, Decimal("0")) + fine.amount.amount

    return [
        FineReviewGroup(
            key=store_key,
            store=labels[store_key],
            count_text=f"{len(rows)} cərimə",
            total_text=_amount_text(totals[store_key]),
            rows=tuple(rows),
        )
        for store_key, rows in sorted(buckets.items(), key=lambda item: labels[item[0]])
    ]


def _to_row(fine: Fine, names: dict[str, dict[str, str]], unsynced: set[FineId]) -> FineReviewRow:
    """`Fine` → ekranın FAKTİKİ gözlədiyi sətir.

    Açarlar HƏM maket (`preview_data.FINE_REVIEW_GROUPS`), HƏM canlı yol üçün
    eynidir — CLAUDE.md §6 (burada `NamedTuple` işlədilir, yəni uyğunsuzluğu
    tip yoxlayıcısı da tutur).
    """
    from src.domain.entities.fine import FineSource  # noqa: PLC0415

    employee_key = str(fine.employee_id)
    operator_key = str(fine.issued_by) if fine.issued_by is not None else ""
    type_key = str(fine.fine_type_id) if fine.fine_type_id is not None else ""
    return FineReviewRow(
        fine_id=str(fine.id),
        employee=names["employees"].get(employee_key) or _short(employee_key),
        # Növü olmayan cərimə AVTOMATİK gecikmə cəriməsidir (`AUTO_DELAY`) —
        # onun kataloq sətri yoxdur və "—" yazmaq mənbəyi gizlədərdi.
        fine_type=names["fine_types"].get(type_key) or _source_label(fine),
        amount_text=_amount_text(fine.amount.amount),
        date_text=fine.issued_at.astimezone().strftime("%d.%m.%Y"),
        # Avtomatik cərimədə operator YOXDUR — sistem yazıb.
        operator=names["employees"].get(operator_key) or "Sistem (avtomatik)",
        # DEEP-GAP T3 — AUTO_DELAY-də sübut anlayışı YOXDUR (əvvəlki halda da
        # `photo_evidence_url` orada `None` idi, yəni nəticə DƏYİŞMİR — sadəcə
        # artıq TƏSADÜFƏN yox, QƏSDƏN). Köhnə (miqrasiya 002-dən əvvəlki)
        # sətirlər `unsynced`-ə DÜŞMÜR (sütun defolt `'SYNCED'`-dir), ona görə
        # onlara retroaktiv "sübutsuz" damğası VURULMUR.
        has_evidence=fine.source is FineSource.MANUAL_CAMERA and fine.id not in unsynced,
    )


def _source_label(fine: Fine) -> str:
    """Kataloq növü olmayan cərimənin mənbəyi — `FineSource` dəyərindən."""
    from src.domain.entities.fine import FineSource  # noqa: PLC0415

    if fine.source is FineSource.AUTO_DELAY:
        return "Gecikmə (avtomatik)"
    return "Kamera qeydi"


def _short(identifier: str) -> str:
    """Adı tapılmayan qeyd üçün qısa identifikator — sətir GİZLƏDİLMİR."""
    return f"#{identifier[:8]}"


__all__ = [
    "DISCARD_PROMPT",
    "EMPTY_BATCH",
    "LIST_CHANGED",
    "LIST_READ_FAILED",
    "PUBLISH_FAILED",
    "SHORT_REASON",
    "UNKNOWN_DECISION",
    "MonthlyFineReviewController",
    "decision_options",
]
