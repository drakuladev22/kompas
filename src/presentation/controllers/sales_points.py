"""Satış Xallarının YAZI yolu — mükafat sorğusu və xal etirazı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`screen_data._sales_points` başlığı bu kontrolleri ADLA vəd edirdi: «YAZI
yolu (`appeal_requested`, `reward_requested`) burada QOŞULMUR — onlar
`points_ledger`-ə yazır və hər yazıdan sonra siyahı yenidən oxunmalıdır, yəni
öz kontrollerini tələb edir». Kontroller isə yazılmamışdı — yəni iki düymə
(«Al» və «Etiraz») ekranda vardı, basılırdı, heç nə olmurdu.

Nəticəsi işçi üçün birbaşa maddi idi: səhv hesablanmış xala etiraz etmək
72 saatlıq pəncərəyə bağlıdır və o pəncərə düymə işləmədiyi üçün sükutla
bağlanırdı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SİQNAL YÜKLƏRİ DƏYİŞDİ
──────────────────────────────────────────────────────────────────────────────
Köhnə ekran `reward_requested` ilə mükafatın ADINI, `appeal_requested` ilə isə
HEÇ NƏ yaymırdı. Use case-lər isə `reward_id` və `entry_id` tələb edir. Yəni
bağlantı texniki olaraq mümkün deyildi: ad təkrarlana bilər, «hansı sətrə
etiraz?» sualının isə cavabı yox idi. Ekran indi identifikator daşıyır və
etiraz düyməsi SƏTİRDƏDİR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from src.domain.value_objects.identifiers import PointsEntryId, RedemptionId, RewardId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_f import SalesPointsScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class SalesPointsController:
    """«Al» və «Etiraz» düymələrini `SalesPointsUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: SalesPointsScreen) -> None:
        screen.reward_requested.connect(lambda key: self._on_reward(screen, key))
        screen.appeal_requested.connect(lambda key: self._on_appeal(screen, key))

    # ------------------------------ mükafat ---------------------------------- #

    def _on_reward(self, screen: SalesPointsScreen, reward_id: str) -> None:
        """«Al» — balans MÜBADİLƏ ANINDA yoxlanılır (use case qaydası).

        Ekran düyməni «Çatmır» halında onsuz da söndürür, lakin bu, YALNIZ
        görüntüdür: ekran açıq qaldıqca balans dəyişə bilər (məs. başqa
        mükafat təsdiqlənir). Qərarı use case verir.
        """

        def run(session: Session) -> None:
            session.sales_points.request_reward(
                tenant_id=session.tenant_id,
                actor=self._actor,
                reward_id=RewardId(UUID(reward_id)),
                # `redemption_id` ÇAĞIRAN TƏRƏFDƏN gəlir: use case-in özü
                # yaratsaydı, təkrar göndərmə (ikiqat klik) İKİ sətir yazardı.
                redemption_id=RedemptionId(uuid4()),
            )

        self._write(screen, run, failure="Mükafat sorğusu göndərilmədi")

    # ------------------------------- etiraz ---------------------------------- #

    def _on_appeal(self, screen: SalesPointsScreen, entry_id: str) -> None:
        reason = self._ask_reason(screen)
        if reason is None:
            return

        def run(session: Session) -> None:
            session.sales_points.open_dispute(
                tenant_id=session.tenant_id,
                actor=self._actor,
                entry_id=PointsEntryId(UUID(entry_id)),
                reason=reason,
            )

        self._write(screen, run, failure="Etiraz göndərilmədi")

    @staticmethod
    def _ask_reason(screen: SalesPointsScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            "Xala etiraz",
            "Səbəb (məcburi) — hansı satışın/tapşırığın səhv hesablandığını\n"
            "yazın; qərar verən şəxs məhz bu mətni oxuyur:",
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None

    # -------------------------------- yazı ----------------------------------- #

    def _write(self, screen: SalesPointsScreen, action: Any, *, failure: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                action(session)
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("SALES_POINTS_WRITE_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title=failure,
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )
            return
        self.refresh(screen)

    def refresh(self, screen: SalesPointsScreen) -> None:
        """Balans, tarixçə və kataloq — MÖVCUD oxu yolundan.

        Yazıdan sonra üçü də dəyişir: mükafat sorğusu balansı bloklayır,
        etiraz isə sətrin vəziyyətini «Etiraz baxılır»-a keçirir.
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        try:
            ScreenDataBinder(self._context, self._actor).populate("sales_points", screen)
        except KompasOSError as exc:
            _error_log.exception("SALES_POINTS_REFRESH_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Xal məlumatı oxuna bilmədi",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )


__all__ = ["SalesPointsController"]
