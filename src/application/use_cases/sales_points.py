"""Satış xalları, mükafat mübadiləsi və 6 aylıq sıfırlanma (bölmə 6).

──────────────────────────────────────────────────────────────────────────────
DÖRD AYRI AXIN, BİR SƏLAHİYYƏT
──────────────────────────────────────────────────────────────────────────────
`can_manage_sales_points` (bölmə 3) üç şeyi əhatə edir: xalları əl ilə
düzəltmək, mükafat mübadiləsini təsdiqləmək, xal etirazlarına baxmaq.
Dördüncü axın — sıfırlanma bildirişi — İNSAN AKTORU OLMAYAN planlayıcı işidir
və səlahiyyət yoxlamır.

İşçinin ÖZ əməliyyatları (balansına baxmaq, etiraz göndərmək, mükafat
istəmək) də səlahiyyət tələb etmir — onlar sahiblik yoxlaması ilə qorunur:
`employee_id` özününküdürsə icazəlidir.

──────────────────────────────────────────────────────────────────────────────
BALANS NİYƏ HESABLANIR, SAXLANMIR
──────────────────────────────────────────────────────────────────────────────
`points_ledger` sətirlərinin cəmi balansdır. Ayrıca `balance` sütunu olsaydı,
`REVERSED` sətir və sütun arasında uyğunsuzluq riski yaranardı və "hansı
doğrudur?" sualı auditdə cavabsız qalardı. Cəm sorğusu bir indeks ilə
sürətlidir; uyğunsuzluq isə düzəlməzdir.

──────────────────────────────────────────────────────────────────────────────
SIFIRLANMA "SİLMƏ" DEYİL
──────────────────────────────────────────────────────────────────────────────
6 aylıq sıfırlanma heç bir sətri silmir və heç bir sətri dəyişmir — sadəcə
balans hesablanan DÖVR dəyişir (bax `PointsPeriod` izahı). Bu use case-in
sıfırlanma tərəfindəki YEGANƏ işi 14 günlük bildirişi vaxtında göndərməkdir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.application.root_limits import limit_decimal, limit_int
from src.domain.entities.sales_points import PointsEntry, RewardRedemption
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.erp import MatchConfidence
from src.domain.value_objects.gamification import (
    PointsBalance,
    PointsEntryStatus,
    PointsPeriod,
    RedemptionStatus,
    points_for_amount,
)
from src.domain.value_objects.identifiers import new_points_entry_id
from src.domain.value_objects.money import Money
from src.domain.value_objects.notifications import NotificationCategory
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        FeatureToggles,
        Notifier,
        RewardRepository,
        SalesPointsRepository,
        SystemLimits,
    )
    from src.domain.value_objects.gamification import RewardItem
    from src.domain.value_objects.identifiers import (
        EmployeeId,
        PointsEntryId,
        RedemptionId,
        RewardId,
        SalesTransactionId,
        StoreId,
        TenantId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_app_log = get_logger(__name__)

MANAGE_POINTS_FLAG = "can_manage_sales_points"


class SalesPointsError(KompasOSError):
    """Xal/mükafat əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class PointsEntryNotFoundError(SalesPointsError):
    user_message = "Xal qeydi tapılmadı."


class RedemptionNotFoundError(SalesPointsError):
    user_message = "Mükafat sorğusu tapılmadı."


@dataclass
class ResetNoticeResult:
    """14 günlük bildiriş dövrünün nəticəsi."""

    period: PointsPeriod | None = None
    notified: list[EmployeeId] = field(default_factory=list)
    skipped_zero_balance: int = 0

    @property
    def notified_count(self) -> int:
        return len(self.notified)


class SalesPointsUseCase:
    """Xal balansı, etiraz axını, mükafat mübadiləsi və sıfırlanma bildirişi."""

    def __init__(
        self,
        *,
        points: SalesPointsRepository,
        rewards: RewardRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        toggles: FeatureToggles | None = None,
        limits: SystemLimits | None = None,
    ) -> None:
        """
        Args:
            limits: Xal sisteminin ÜÇ ROOT parametrinə açılan pəncərə —
                `SALES_POINTS_CURRENCY_PER_POINT` (neçə AZN = 1 xal),
                `SALES_POINTS_RESET_NOTICE_DAYS` və
                `SALES_POINTS_DISPUTE_WINDOW_HOURS`. Faza 10.2-nin birinci
                dalğası bu açarları YARATDI, lakin bu use case onları OXUMURDU
                — yəni ekranda görünən, dəyişdirilən, TƏSİRSİZ parametrlər idi
                (`gamification.py` şərhi hətta "ROOT-dan idarə olunur"
                deyirdi). Bu sahə həmin halqanı bağlayır. `toggles` ilə eyni
                İSTƏYƏ BAĞLI naxış: `None` → domen fallback-ları, davranış
                köçürmədən ƏVVƏLKİ ilə HƏRFƏN eyni.
        """
        self._points = points
        self._rewards = rewards
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        # `None` → fail-open (bax `task_workflow.py` eyni sahə şərhi).
        self._toggles = toggles
        self._limits = limits

    # ---------------------------- ROOT parametrləri --------------------------- #

    def _currency_per_point(self, tenant_id: TenantId) -> Decimal:
        """Neçə AZN brutto satış 1 xal qazandırır (ROOT parametri).

        ÇAĞIRIŞ ANINDA oxunur: kampaniya dövründə Root kursu dəyişdirən kimi
        növbəti sinxronizasiya yeni kursla xal yazmalıdır.
        """
        return limit_decimal(
            self._limits, tenant_id, SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT
        )

    def _dispute_window_hours(self, tenant_id: TenantId) -> int:
        """Xal etirazı pəncərəsi (ROOT parametri, cərimə pəncərəsindən AYRI).

        Sətrin ÖZÜNƏ yazılır (`PointsEntry.dispute_window_hours`), çünki
        pəncərə `awarded_at`-dan sayılır: sonradan dəyişən Root dəyəri artıq
        yazılmış sətirlərin müddətini geriyə dönüb uzatmamalı/qısaltmamalıdır.
        """
        return limit_int(self._limits, tenant_id, SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS)

    # -------------------------------- balans --------------------------------- #

    def balance_for(
        self, employee_id: EmployeeId, *, tenant_id: TenantId, period: PointsPeriod | None = None
    ) -> PointsBalance:
        """İşçinin cari dövr balansı — bloklanmış xallar çıxılmış."""
        now = self._clock.now()
        window = period or PointsPeriod.containing(now.date())

        earned = sum(
            entry.effective_points
            for entry in self._points.list_for_employee(employee_id, period=window)
        )
        held = sum(
            redemption.cost_points
            for redemption in self._rewards.list_redemptions(tenant_id)
            if redemption.employee_id == employee_id and redemption.holds_points
        )
        # Kataloq qiyməti sonradan qalxsa, bloklanmış cəm qazanılandan çox
        # görünə bilər. Balans obyektinin yaranmaması ekranı tamamilə
        # bloklayardı, ona görə burada məhdudlaşdırılır və hadisə loglanır.
        if held > earned:
            _app_log.warning(
                "POINTS_HELD_EXCEEDS_EARNED",
                extra={"employee_id": str(employee_id), "earned": earned, "held": held},
            )
            held = earned

        return PointsBalance(period=window, earned=earned, held=held)

    # -------------------------------- etiraz --------------------------------- #

    def open_dispute(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        entry_id: PointsEntryId,
        reason: str,
    ) -> PointsEntry:
        """İşçi öz xal sətrinə 72 saat ərzində etiraz edir.

        SAHİBLİK yoxlanılır, səlahiyyət yox: bu, işçinin öz hüququdur.
        """
        now = self._clock.now()
        entry = self._load_entry(entry_id)

        if entry.employee_id != actor.id:
            _audit_log.warning(
                "POINTS_FOREIGN_DISPUTE_BLOCKED",
                extra={"actor_id": str(actor.id), "entry_id": str(entry_id)},
            )
            raise SalesPointsError(
                "Yalnız öz xal qeydinə etiraz etmək olar",
                user_message="Bu qeyd sizə aid deyil.",
            )

        entry.open_dispute(reason=reason, disputed_at=now)
        self._points.save(entry)
        entry.collect_events()

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POINTS_DISPUTE_OPENED",
            entity_type="points_entry",
            entity_id=entry.id,
            after_state={"status": entry.status.value, "points": entry.points},
            reason=entry.dispute_reason,
        )
        return entry

    def decide_dispute(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        entry_id: PointsEntryId,
        reason: str,
        corrected_points: int | None = None,
        reject: bool = False,
    ) -> PointsEntry:
        """`can_manage_sales_points` sahibinin qərarı.

        Üç nəticə: rədd (sətir qüvvədə qalır), korreksiya (yeni dəyər), tam
        ləğv (`corrected_points=0` ötürülməsi `reverse()`-ə yönləndirilir —
        ekran istifadəçisi "sıfır" yazdıqda niyyəti tam ləğvdir).
        """
        now = self._clock.now()
        self._require(actor, now=now)
        entry = self._load_entry(entry_id)

        before: dict[str, object] = {"status": entry.status.value, "points": entry.points}

        if reject:
            entry.reject_dispute(decided_by=actor.id, decided_at=now, reason=reason)
            action = "POINTS_DISPUTE_REJECTED"
        elif corrected_points is None or corrected_points == 0:
            entry.reverse(decided_by=actor.id, decided_at=now, reason=reason)
            action = "POINTS_REVERSED"
        else:
            entry.correct(
                new_points=corrected_points,
                decided_by=actor.id,
                decided_at=now,
                reason=reason,
            )
            action = "POINTS_CORRECTED"

        self._points.save(entry)
        entry.collect_events()

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action=action,
            entity_type="points_entry",
            entity_id=entry.id,
            before_state=before,
            after_state={
                "status": entry.status.value,
                "points": entry.points,
                "original_points": entry.original_points,
            },
            reason=entry.decision_reason,
        )
        self._safe_notify(
            tenant_id=tenant_id,
            recipient=entry.employee_id,
            title="Xal etirazınız üzrə qərar verildi",
            body=f"Nəticə: {entry.status.value}. Səbəb: {entry.decision_reason}",
        )
        return entry

    # ------------------------------ mükafat ---------------------------------- #

    def request_reward(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        reward_id: RewardId,
        redemption_id: RedemptionId,
    ) -> RewardRedemption:
        """İşçi mükafat istəyir — balans MÜBADİLƏ ANINDA yoxlanılır.

        RETROAKTİV TƏSİR QAYDASI: `SALES_POINTS` söndürülübsə YENİ sorğu
        qəbul edilmir, lakin gözləyən sorğular `decide_reward` ilə normal
        qərar alır və qazanılmış xallar toxunulmaz qalır.
        """
        now = self._clock.now()
        self._require_module(tenant_id)
        reward = self._rewards.get_reward(reward_id)
        if reward is None:
            raise RedemptionNotFoundError(
                f"Mükafat tapılmadı: {reward_id}",
                user_message="Bu mükafat kataloqda yoxdur.",
            )

        balance = self.balance_for(actor.id, tenant_id=tenant_id)
        redemption = RewardRedemption(
            redemption_id=redemption_id,
            tenant_id=tenant_id,
            employee_id=actor.id,
            reward_id=reward_id,
            reward=reward,
            available_points=balance.available,
            requested_at=now,
        )
        self._rewards.save_redemption(redemption)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="REWARD_REQUESTED",
            entity_type="reward_redemption",
            entity_id=redemption.id,
            after_state={
                "reward": redemption.reward_name,
                "cost_points": redemption.cost_points,
                "available_before": balance.available,
            },
        )
        return redemption

    def decide_reward(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        redemption_id: RedemptionId,
        approve: bool,
        reason: str = "",
    ) -> RewardRedemption:
        """`can_manage_sales_points` sahibi mübadiləni təsdiqləyir/rədd edir."""
        now = self._clock.now()
        self._require(actor, now=now)

        redemption = self._rewards.get_redemption(redemption_id)
        if redemption is None:
            raise RedemptionNotFoundError(
                f"Mükafat sorğusu tapılmadı: {redemption_id}",
                context={"redemption_id": str(redemption_id)},
            )

        if approve:
            redemption.approve(decided_by=actor.id, decided_at=now)
        else:
            redemption.reject(decided_by=actor.id, decided_at=now, reason=reason)

        self._rewards.save_redemption(redemption)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="REWARD_APPROVED" if approve else "REWARD_REJECTED",
            entity_type="reward_redemption",
            entity_id=redemption.id,
            after_state={"status": redemption.status.value},
            reason=redemption.decision_reason,
        )
        self._safe_notify(
            tenant_id=tenant_id,
            recipient=redemption.employee_id,
            title="Mükafat sorğunuz",
            body=(f"{redemption.reward_name} — {'təsdiqləndi' if approve else 'rədd edildi'}"),
        )
        return redemption

    def list_pending_rewards(
        self, *, tenant_id: TenantId, actor: Employee
    ) -> list[RewardRedemption]:
        """Təsdiq gözləyən mübadilə sorğuları — idarəetmə inbox-u."""
        self._require(actor, now=self._clock.now())
        return [
            redemption
            for redemption in self._rewards.list_redemptions(tenant_id, pending_only=True)
            if redemption.status is RedemptionStatus.REQUESTED
        ]

    def list_rewards_for_employee(self, tenant_id: TenantId) -> list[tuple[RewardId, RewardItem]]:
        """İşçinin gördüyü mükafat kataloqu — YALNIZ aktivlər."""
        return self._rewards.list_rewards(tenant_id, include_inactive=False)

    # ------------------------ şübhəli satışın köçürülməsi -------------------- #

    def transfer_for_transaction(
        self,
        *,
        tenant_id: TenantId,
        transaction_id: SalesTransactionId,
        from_employee_id: EmployeeId | None,
        to_employee_id: EmployeeId,
        store_id: StoreId,
        gross_amount: Decimal,
        actor_id: EmployeeId,
        reason: str,
    ) -> None:
        """«Şübhəli Satışlar» növbəsindən gələn yenidən-təyinat (bölmə 6).

        Səlahiyyət BURADA yoxlanılmır — çağıran `SalesReviewQueueUseCase`
        `can_manage_sales_points`-i artıq yoxlayıb. İkinci yoxlama zərərsiz
        olardı, amma o zaman bu metod `Employee` obyekti tələb edərdi və
        `PointsAdjuster` protokolu iki use case-i bir-birinə bağlayardı.

        İKİ ADDIM, HƏR İKİSİ AUDİT-Lİ:
            1. Köhnə sahibin sətri `REVERSED` olur (silinmir — bölmə 6).
            2. Yeni sahibə eyni dəyərdə YENİ sətir yazılır.

        Xalı "köçürmək" (sətrin `employee_id`-sini dəyişmək) rədd edildi:
        ledger append-only-dır və köhnə sahibin balans tarixçəsi geriyə dönüb
        dəyişsəydi, onun artıq gördüyü balans izahsız azalardı.
        """
        now = self._clock.now()
        period = PointsPeriod.containing(now.date())
        moved_points = 0

        if from_employee_id is not None:
            for entry in self._points.list_for_employee(from_employee_id, period=period):
                if entry.sales_transaction_id != transaction_id:
                    continue
                if entry.status is not PointsEntryStatus.ACTIVE:
                    continue
                moved_points = entry.effective_points
                entry.reverse(decided_by=actor_id, decided_at=now, reason=reason)
                self._points.save(entry)
                break

        if moved_points <= 0:
            # Köhnə sahib yox idi (UNASSIGNED) və ya sətri tapılmadı —
            # xal məbləğdən yenidən hesablanır. Kurs ROOT-dan oxunur ki,
            # köçürmə ilə ilkin yazma EYNİ qaydaya tabe olsun (əvvəl burada
            # domen fallback-ı işlədilirdi və Root kursu dəyişəndə köçürülən
            # xal sükutla köhnə kursla hesablanırdı).
            moved_points = points_for_amount(
                gross_amount, currency_per_point=self._currency_per_point(tenant_id)
            )

        if moved_points <= 0:
            _app_log.info(
                "POINTS_TRANSFER_SKIPPED_ZERO",
                extra={"transaction_id": str(transaction_id)},
            )
            return

        replacement = PointsEntry(
            entry_id=new_points_entry_id(),
            tenant_id=tenant_id,
            employee_id=to_employee_id,
            store_id=store_id,
            points=moved_points,
            awarded_at=now,
            confidence=MatchConfidence.MANUAL_MATCH,
            sales_transaction_id=transaction_id,
            gross_amount=Money(gross_amount),
            dispute_window_hours=self._dispute_window_hours(tenant_id),
        )
        self._points.save(replacement)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="POINTS_TRANSFERRED",
            entity_type="points_ledger",
            entity_id=replacement.id,
            before_state={
                "employee_id": str(from_employee_id) if from_employee_id else None,
                "transaction_id": str(transaction_id),
            },
            after_state={
                "employee_id": str(to_employee_id),
                "points": moved_points,
            },
            reason=reason,
        )

    # ------------------------- satışdan xal verilməsi ------------------------ #

    def award_for_sale(
        self,
        *,
        tenant_id: TenantId,
        employee_id: EmployeeId,
        store_id: StoreId,
        transaction_id: SalesTransactionId,
        gross_amount: Decimal,
        confidence: MatchConfidence = MatchConfidence.EXACT_MATCH,
        currency_per_point: Decimal | None = None,
    ) -> PointsEntry | None:
        """Sinxronlaşdırılmış satışdan xal yazır (bölmə 6).

        `None` qaytarır və HEÇ NƏ yazmır iki halda: məbləğ bir xala çatmır,
        və ya uyğunlaşma xal qazandırmır (`UNASSIGNED`). Sıfır xallı sətir
        yaratmaq ledger-i mənasız sətirlərlə doldurardı və `PointsEntry`
        onsuz da müsbət dəyər tələb edir.
        """
        if not confidence.awards_points:
            return None
        # Modul söndürülübsə YENİ xal yazılmır (tarixi sətirlər qalır).
        if self._toggles is not None and not self._toggles.is_enabled(
            tenant_id, FeatureModule.SALES_POINTS.value
        ):
            return None

        # AÇIQ ARQUMENT > ROOT > domen fallback-ı. Açıq arqument saxlanılıb:
        # yenidən-hesablama skripti keçmiş dövrü ÖZ kursu ilə emal etməlidir.
        rate = (
            self._currency_per_point(tenant_id)
            if currency_per_point is None
            else (currency_per_point)
        )
        earned = points_for_amount(gross_amount, currency_per_point=rate)
        if earned <= 0:
            return None

        entry = PointsEntry(
            entry_id=new_points_entry_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            store_id=store_id,
            points=earned,
            awarded_at=self._clock.now(),
            confidence=confidence,
            sales_transaction_id=transaction_id,
            gross_amount=Money(gross_amount),
            dispute_window_hours=self._dispute_window_hours(tenant_id),
        )
        self._points.save(entry)
        return entry

    # ---------------------------- sıfırlanma bildirişi ----------------------- #

    def send_reset_notices(
        self,
        *,
        tenant_id: TenantId,
        employee_ids: list[EmployeeId],
        notice_days: int | None = None,
    ) -> ResetNoticeResult:
        """1 Yanvar / 1 İyul sıfırlanmasından 14 gün əvvəl xəbərdarlıq (bölmə 6).

        Balansı SIFIR olan işçiyə bildiriş GETMİR: "0 xalınız sıfırlanacaq"
        mesajı məlumat vermir, sadəcə bildiriş siyahısını doldurur və real
        xəbərdarlıqların görünməsini çətinləşdirir.
        """
        now = self._clock.now()
        today = now.date()
        period = PointsPeriod.containing(today)
        result = ResetNoticeResult(period=period)

        # `None` → ROOT parametri (`SALES_POINTS_RESET_NOTICE_DAYS`); açıq
        # arqument onu əvəz edir (əl ilə "indi xəbərdar et" icrası üçün).
        applied_notice_days = (
            limit_int(self._limits, tenant_id, SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS)
            if notice_days is None
            else notice_days
        )
        if not period.is_notice_due(today, notice_days=applied_notice_days):
            return result

        for employee_id in employee_ids:
            balance = self.balance_for(employee_id, tenant_id=tenant_id, period=period)
            if balance.available <= 0:
                result.skipped_zero_balance += 1
                continue

            days_left = balance.days_until_reset(today=today)
            self._safe_notify(
                tenant_id=tenant_id,
                recipient=employee_id,
                title="Satış xallarınız sıfırlanacaq",
                body=(
                    f"{balance.available} xalınız {days_left} gün sonra "
                    f"({period.reset_on:%d.%m.%Y}) sıfırlanacaq. "
                    f"Mükafat kataloqundan istifadə edin."
                ),
                category=NotificationCategory.POINTS_RESET_UPCOMING,
            )
            result.notified.append(employee_id)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,
            action="POINTS_RESET_NOTICE_SENT",
            entity_type="points_period",
            entity_id=period.label_az(),
            after_state={
                "notified": result.notified_count,
                "skipped_zero_balance": result.skipped_zero_balance,
                "reset_on": period.reset_on.isoformat(),
            },
        )
        return result

    # ------------------------------- köməkçilər ------------------------------ #

    def _load_entry(self, entry_id: PointsEntryId) -> PointsEntry:
        entry = self._points.get(entry_id)
        if entry is None:
            raise PointsEntryNotFoundError(
                f"Xal qeydi tapılmadı: {entry_id}", context={"entry_id": str(entry_id)}
            )
        return entry

    def _require_module(self, tenant_id: TenantId) -> None:
        """`SALES_POINTS` Feature Toggle qapısı (bölmə 3)."""
        if self._toggles is None:
            return
        if not self._toggles.is_enabled(tenant_id, FeatureModule.SALES_POINTS.value):
            raise SalesPointsError(
                "SALES_POINTS modulu deaktiv edilib",
                user_message="Satış xalları modulu hazırda aktiv deyil.",
                context={"module": FeatureModule.SALES_POINTS.value},
            )

    def _require(self, actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(MANAGE_POINTS_FLAG, now=now):
            _audit_log.warning(
                "POINTS_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_POINTS_FLAG},
            )
            raise SalesPointsError(
                f"«{MANAGE_POINTS_FLAG}» səlahiyyəti yoxdur",
                user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
            )

    def _safe_notify(
        self,
        *,
        tenant_id: TenantId,
        recipient: EmployeeId,
        title: str,
        body: str,
        category: NotificationCategory = NotificationCategory.POINTS_RESET_UPCOMING,
    ) -> None:
        """Bildiriş uğursuzluğu ƏSAS əməliyyatı geri qaytarmır.

        Xal artıq düzəldilib və audit-ə yazılıb; e-poçt serverinin əlçatmaz
        olması həmin qərarı ləğv etməməlidir.
        """
        try:
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=recipient,
                category=category.value,
                title_az=title,
                body_az=body,
                is_critical=category.is_always_critical,
            )
        except Exception:
            _app_log.exception("POINTS_NOTIFY_FAILED", extra={"recipient_id": str(recipient)})


__all__ = [
    "MANAGE_POINTS_FLAG",
    "PointsEntryNotFoundError",
    "RedemptionNotFoundError",
    "ResetNoticeResult",
    "SalesPointsError",
    "SalesPointsUseCase",
]
