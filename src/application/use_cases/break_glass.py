"""Break-glass fövqəladə giriş — `v2backlog.md` Faza 5.4.

    "Root əlçatmaz olanda, ƏVVƏLCƏDƏN təyin edilmiş bir ehtiyat-admin, xüsusi
     audit-lənən bir axınla müvəqqəti Root-səlahiyyəti ala bilir. Bu, YÜKSƏK-
     RİSKLİ bir funksiyadır — hər istifadə mərkəzi vendor bazasına da yazılsın."

──────────────────────────────────────────────────────────────────────────────
AXIN
──────────────────────────────────────────────────────────────────────────────
  Root (əvvəlcədən)  designate_trustee()   → `break_glass_trustees`
  Ehtiyat-admin      request_access()      → `PENDING_APPROVAL` + bildiriş
  İkinci şəxs        approve() / reject()  → `ACTIVE` (vaxt-məhdud) / `REJECTED`
  Root (qayıdanda)   revoke()              → `REVOKED`
  Planlayıcı         expire_due()          → `EXPIRED` (iki növ: pəncərə, müddət)

──────────────────────────────────────────────────────────────────────────────
«MÜVƏQQƏTİ ROOT SƏLAHİYYƏTİ» NƏ DEMƏKDİR — DƏQİQ TƏRİFİ
──────────────────────────────────────────────────────────────────────────────
`has_effective_root()` YEGANƏ giriş nöqtəsidir: aktiv qrantı olan işçi üçün
`True` qaytarır. Bu metod işçinin `position`-una VƏ `permission_flags`-inə
TOXUNMUR (səbəb `entities/break_glass.py` başlığındadır: geri qaytarmağı
unutmaq mümkün olmamalıdır).

BUNUN NƏTİCƏSİ AÇIQ SƏNƏDLƏŞDİRİLİR: break-glass səlahiyyəti YALNIZ onu
soruşan yollarda işləyir. Bu, ZƏİFLİK DEYİL, QƏSDLİ DARALDILMADIR — fövqəladə
giriş bütün 58 flag-i birdən açsaydı, o, «böhran açarı» yox, ikinci daimi
Root hesabı olardı. Çağıran tərəf (məs. `RecoveryConsoleController`) bu metodu
AÇIQ soruşur və auditə YAZIR.

──────────────────────────────────────────────────────────────────────────────
VENDOR BİLDİRİŞİ NİYƏ ƏMƏLİYYATI BLOKLAMIR
──────────────────────────────────────────────────────────────────────────────
`VendorBreakGlassReporter.report()` uğursuz olarsa təsdiq GERİ QAYTARILMIR —
sətir `vendor_synced_at IS NULL` qalır və gecəlik iş yenidən cəhd edir.
Bu, `AuditTrail.record()` qaydasının (CLAUDE.md §5: audit istisna UDMUR)
İSTİSNASIDIR və səbəbi budur: yerli audit sətri EYNİ tranzaksiyadadır və
zəmanətlidir; vendor bildirişi isə XARİCİ şəbəkə çağırışıdır və məhz
fövqəladə halda (internet kəsilib, ona görə Root əlçatmazdır) uğursuz olma
ehtimalı ƏN YÜKSƏKDİR. Onu bloklayıcı etmək funksiyanı lazım olduğu anda
işləməz edərdi.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.application.root_limits import limit_int
from src.domain.entities.break_glass import (
    BreakGlassGrant,
    BreakGlassStatus,
    BreakGlassTrustee,
)
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.identifiers import (
    new_break_glass_grant_id,
    new_break_glass_trustee_id,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        BreakGlassRepository,
        Clock,
        EmployeeRepository,
        Notifier,
        SystemLimits,
        VendorBreakGlassReporter,
    )
    from src.domain.value_objects.identifiers import (
        BreakGlassGrantId,
        EmployeeId,
        TenantId,
    )

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Reyestri idarə edən flag — YALNIZ Root (`hardlock_level=1`, migrations/100).
MANAGE_BREAK_GLASS_FLAG = "can_manage_break_glass"
#: İkinci-etibarlı şəxs qapısı — Root VƏ CEO (`hardlock_level=2`).
APPROVE_BREAK_GLASS_FLAG = "can_approve_break_glass"

#: Gecəlik vendor təkrar-cəhdinin bir dövrədə götürdüyü sətir sayı.
#:
#: ROOT PARAMETRİ DEYİL: bu, şəbəkə çağırışının paket ölçüsüdür, siyasət yox
#: (`OFFLINE_SYNC_BATCH_SIZE` ilə eyni növ ədəd, lakin break-glass sətirləri
#: ayda 1-2 dənədir — həddin praktikada heç vaxt toxunulmayacağı gözlənilir
#: və ona görə ayrıca Root açarı yaratmaq mənasız təkrar olardı).
VENDOR_RETRY_BATCH = 50


class BreakGlassError(KompasOSError):
    """Fövqəladə giriş əməliyyatı icra edilə bilmədi."""

    user_message = "Fövqəladə giriş əməliyyatı icra edilə bilmədi."


class BreakGlassPermissionError(BreakGlassError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


class BreakGlassNotFoundError(BreakGlassError):
    user_message = "Bu fövqəladə giriş sorğusu tapılmadı."


class BreakGlassUseCase:
    """Ehtiyat-admin reyestri + vaxt-məhdud fövqəladə səlahiyyət."""

    def __init__(
        self,
        *,
        grants: BreakGlassRepository,
        employees: EmployeeRepository,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        limits: SystemLimits | None = None,
        vendor_reporter: VendorBreakGlassReporter | None = None,
    ) -> None:
        self._grants = grants
        self._employees = employees
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        self._limits = limits
        # İSTƏYƏ BAĞLI: özünə-host quraşdırmada mərkəzi vendor bazası olmaya
        # bilər (`.env.example`-in `KOMPASOS_PRIVATE_SERVER_DSN` naxışı).
        # `None` = bildiriş göndərilmir, sətir yerli olaraq TAM qalır.
        self._vendor = vendor_reporter

    # ----------------------------- REYESTR ----------------------------------- #

    def designate_trustee(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId
    ) -> BreakGlassTrustee:
        """Root ehtiyat-admin təyin edir — BÖHRANDAN ƏVVƏL."""
        self._require(actor, MANAGE_BREAK_GLASS_FLAG)
        target = self._employees.get(employee_id)
        if target is None or target.tenant_id != tenant_id:
            raise BreakGlassError(
                "Ehtiyat-admin olaraq təyin ediləcək işçi tapılmadı",
                user_message="Seçilmiş işçi tapılmadı.",
                context={"employee_id": str(employee_id)},
            )
        if not target.is_active:
            raise BreakGlassError(
                "Deaktiv işçi ehtiyat-admin ola bilməz",
                user_message="Yalnız aktiv işçi ehtiyat-admin təyin edilə bilər.",
                context={"employee_id": str(employee_id)},
            )
        if self._grants.find_trustee(tenant_id, employee_id) is not None:
            raise BreakGlassError(
                "İşçi artıq ehtiyat-admindir",
                user_message="Bu işçi artıq ehtiyat-admin siyahısındadır.",
                context={"employee_id": str(employee_id)},
            )

        trustee = BreakGlassTrustee(
            trustee_id=new_break_glass_trustee_id(),
            tenant_id=tenant_id,
            employee_id=employee_id,
            designated_by=actor.id,
            designated_at=self._clock.now(),
        )
        self._grants.save_trustee(trustee)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BREAK_GLASS_TRUSTEE_DESIGNATED",
            entity_type="break_glass_trustees",
            entity_id=trustee.id,
            after_state={"employee_id": str(employee_id), "is_active": True},
        )
        # İŞÇİNİN ÖZÜNƏ BİLDİRİŞ GEDİR VƏ BU QƏSDLİDİR: təyinat həmin şəxsə
        # məsuliyyət yükləyir (böhran anında ondan hərəkət gözlənilir) və
        # xəbərsiz təyinat həm işləməz, həm də sui-istifadəni gizlədərdi —
        # kiminsə adına səlahiyyət açılıb, o isə bilmir.
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=employee_id,
            category="BREAK_GLASS_TRUSTEE",
            title_az="Siz ehtiyat-admin təyin edildiniz",
            body_az=(
                "Fövqəladə hallarda (Root əlçatmaz olduqda) müvəqqəti "
                "səlahiyyət tələb edə bilərsiniz. Hər istifadə audit olunur."
            ),
            is_critical=True,
        )
        return trustee

    def revoke_trustee(
        self, *, tenant_id: TenantId, actor: Employee, employee_id: EmployeeId
    ) -> BreakGlassTrustee:
        """Root təyinatı ləğv edir — sətir soft-delete olur."""
        self._require(actor, MANAGE_BREAK_GLASS_FLAG)
        trustee = self._grants.find_trustee(tenant_id, employee_id)
        if trustee is None:
            raise BreakGlassNotFoundError(
                "Aktiv ehtiyat-admin təyinatı tapılmadı",
                user_message="Bu işçi ehtiyat-admin siyahısında deyil.",
                context={"employee_id": str(employee_id)},
            )
        trustee.revoke(revoked_by=actor.id, revoked_at=self._clock.now())
        self._grants.save_trustee(trustee)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BREAK_GLASS_TRUSTEE_REVOKED",
            entity_type="break_glass_trustees",
            entity_id=trustee.id,
            after_state={"employee_id": str(employee_id), "is_active": False},
        )
        return trustee

    def trustees(self, *, tenant_id: TenantId, actor: Employee) -> list[BreakGlassTrustee]:
        """Reyestrin oxunması — `can_manage_break_glass` VƏ ya təsdiqləyici görür.

        Təsdiqləyiciyə də açıqdır, çünki o, gələn sorğunun HƏQİQİ ehtiyat-
        admindən gəldiyini yoxlamalıdır — siyahını görmədən təsdiq «kor
        təsdiq» olardı.
        """
        now = self._clock.now()
        if not (
            actor.has_permission(MANAGE_BREAK_GLASS_FLAG, now=now)
            or actor.has_permission(APPROVE_BREAK_GLASS_FLAG, now=now)
        ):
            raise BreakGlassPermissionError(
                "Ehtiyat-admin reyestrini görmək üçün səlahiyyət yoxdur",
                context={"actor_id": str(actor.id)},
            )
        return self._grants.active_trustees(tenant_id)

    # ------------------------------- SORĞU ----------------------------------- #

    def request_access(
        self, *, tenant_id: TenantId, actor: Employee, reason: str
    ) -> BreakGlassGrant:
        """Ehtiyat-admin fövqəladə səlahiyyət istəyir.

        DÖRD QAPI, BU SIRA İLƏ: reyestrdə olmaq → açıq sorğusu olmamaq →
        aylıq tavanı aşmamaq → səbəbi ətraflı yazmaq (sonuncu domendədir).
        Sıra QƏSDLİDİR: ən ucuz və ən çox rədd edən yoxlama əvvəldədir.
        """
        if self._grants.find_trustee(tenant_id, actor.id) is None:
            # Reyestrdə olmayan şəxsin cəhdi TƏHLÜKƏSİZLİK HADİSƏSİDİR —
            # sadəcə xəta deyil. Jurnal `SECURITY` kanalına yazılır.
            _security_log.warning(
                "BREAK_GLASS_UNAUTHORIZED_REQUEST",
                extra={"actor_id": str(actor.id), "tenant_id": str(tenant_id)},
            )
            raise BreakGlassPermissionError(
                "Yalnız əvvəlcədən təyin edilmiş ehtiyat-admin fövqəladə giriş istəyə bilər",
                user_message=(
                    "Fövqəladə giriş yalnız əvvəlcədən təyin edilmiş ehtiyat-adminlər üçündür."
                ),
                context={"actor_id": str(actor.id)},
            )
        if self._grants.find_open_for_employee(tenant_id, actor.id) is not None:
            raise BreakGlassError(
                "İşçinin artıq açıq fövqəladə giriş sorğusu var",
                user_message="Sizin artıq gözləyən və ya aktiv fövqəladə girişiniz var.",
                context={"actor_id": str(actor.id)},
            )

        now = self._clock.now()
        self._require_monthly_quota(tenant_id, now=now)

        window = limit_int(
            self._limits, tenant_id, SystemLimitKey.BREAK_GLASS_APPROVAL_WINDOW_MINUTES
        )
        grant = BreakGlassGrant(
            grant_id=new_break_glass_grant_id(),
            tenant_id=tenant_id,
            requested_by=actor.id,
            reason=reason,
            requested_at=now,
            approval_expires_at=now + timedelta(minutes=window),
        )
        self._grants.save_grant(grant)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BREAK_GLASS_REQUESTED",
            entity_type="break_glass_grants",
            entity_id=grant.id,
            after_state={
                "status": grant.status.value,
                "approval_expires_at": grant.approval_expires_at.isoformat(),
            },
            reason=grant.reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=None,  # `can_approve_break_glass` sahibləri
            category="BREAK_GLASS_PENDING",
            title_az="FÖVQƏLADƏ GİRİŞ SORĞUSU",
            body_az=(
                f"{actor.full_name} müvəqqəti Root səlahiyyəti istəyir. "
                f"Səbəb: {grant.reason}. Təsdiq üçün {window} dəqiqəniz var."
            ),
            # HƏMİŞƏ kritik: e-poçt fallback-ı məhz burada lazımdır — panelə
            # baxan olmaya bilər, çünki fövqəladə hal iş saatından kənarda
            # baş verir.
            is_critical=True,
        )
        return grant

    # ------------------------------- QƏRAR ----------------------------------- #

    def approve(
        self, *, tenant_id: TenantId, approver: Employee, grant_id: BreakGlassGrantId
    ) -> BreakGlassGrant:
        """İkinci-etibarlı şəxs təsdiqləyir — səlahiyyət BU ANDAN qüvvəyə minir."""
        self._require_approver(tenant_id, approver)
        grant = self._require_grant(tenant_id, grant_id)
        duration = limit_int(
            self._limits, tenant_id, SystemLimitKey.BREAK_GLASS_MAX_DURATION_MINUTES
        )
        grant.approve(
            approver_id=approver.id,
            approved_at=self._clock.now(),
            duration_minutes=duration,
        )
        self._grants.save_grant(grant)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="BREAK_GLASS_APPROVED",
            entity_type="break_glass_grants",
            entity_id=grant.id,
            after_state={
                "status": grant.status.value,
                "requested_by": str(grant.requested_by),
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            },
            reason=grant.reason,
        )
        _security_log.warning(
            "BREAK_GLASS_GRANTED",
            extra={
                "grant_id": str(grant.id),
                "requested_by": str(grant.requested_by),
                "approved_by": str(approver.id),
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            },
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=grant.requested_by,
            category="BREAK_GLASS_DECIDED",
            title_az="Fövqəladə giriş təsdiqləndi",
            body_az=f"Müvəqqəti səlahiyyətiniz {duration} dəqiqə qüvvədədir.",
            is_critical=True,
        )
        self._report_to_vendor(grant)
        return grant

    def reject(
        self,
        *,
        tenant_id: TenantId,
        approver: Employee,
        grant_id: BreakGlassGrantId,
        reason: str,
    ) -> BreakGlassGrant:
        """İkinci-etibarlı şəxs rədd edir."""
        self._require_approver(tenant_id, approver)
        grant = self._require_grant(tenant_id, grant_id)
        grant.reject(approver_id=approver.id, decided_at=self._clock.now(), reason=reason)
        self._grants.save_grant(grant)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=approver.id,
            action="BREAK_GLASS_REJECTED",
            entity_type="break_glass_grants",
            entity_id=grant.id,
            after_state={"status": grant.status.value, "requested_by": str(grant.requested_by)},
            reason=reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=grant.requested_by,
            category="BREAK_GLASS_DECIDED",
            title_az="Fövqəladə giriş rədd edildi",
            body_az=f"Sorğunuz rədd edildi. Səbəb: {reason}",
            is_critical=True,
        )
        # RƏDD DƏ VENDOR-A GEDİR: təkrar-təkrar rədd edilən sorğu ən vacib
        # təhlükəsizlik siqnallarındandır (bax `BreakGlassRequestedEvent`).
        self._report_to_vendor(grant)
        return grant

    def revoke(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        grant_id: BreakGlassGrantId,
        reason: str,
    ) -> BreakGlassGrant:
        """Root qayıdıb aktiv səlahiyyəti vaxtından əvvəl dayandırır."""
        self._require(actor, MANAGE_BREAK_GLASS_FLAG)
        grant = self._require_grant(tenant_id, grant_id, expect_pending=False)
        grant.revoke(revoked_by=actor.id, revoked_at=self._clock.now(), reason=reason)
        self._grants.save_grant(grant)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BREAK_GLASS_REVOKED",
            entity_type="break_glass_grants",
            entity_id=grant.id,
            after_state={"status": grant.status.value, "requested_by": str(grant.requested_by)},
            reason=reason,
        )
        self._notifier.notify(
            tenant_id=tenant_id,
            recipient_id=grant.requested_by,
            category="BREAK_GLASS_DECIDED",
            title_az="Fövqəladə səlahiyyət dayandırıldı",
            body_az=f"Müvəqqəti səlahiyyətiniz dayandırıldı. Səbəb: {reason}",
            is_critical=True,
        )
        self._report_to_vendor(grant)
        return grant

    # ------------------------------- OXUMA ----------------------------------- #

    def pending_inbox(self, *, tenant_id: TenantId, actor: Employee) -> list[BreakGlassGrant]:
        """Təsdiq gözləyən sorğular."""
        self._require_approver(tenant_id, actor)
        return self._grants.list_pending(tenant_id)

    def has_effective_root(
        self, *, tenant_id: TenantId, employee_id: EmployeeId, at: datetime | None = None
    ) -> bool:
        """Bu işçinin BU ANDA qüvvədə olan fövqəladə səlahiyyəti varmı.

        Səlahiyyətin YEGANƏ soruşulma nöqtəsi (bax modul başlığı). Vaxt
        yoxlaması aqreqatın özündədir — planlayıcı gecikəndə də səlahiyyət
        verilmir.
        """
        moment = at if at is not None else self._clock.now()
        grant = self._grants.find_open_for_employee(tenant_id, employee_id)
        return grant is not None and grant.is_effective_at(moment)

    def is_active_trustee(self, *, tenant_id: TenantId, employee_id: EmployeeId) -> bool:
        """Bu işçi AKTİV ehtiyat-admindirmi — YALNIZ MARŞRUTLAMA üçün oxu.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ SƏLAHİYYƏT YOXLAMASI YOXDUR
        ──────────────────────────────────────────────────────────────────────
        Bu metod İCAZƏ VERMİR — menyu maddəsinin görünürlüyünü hesablamaq üçün
        çağırılır (`app.py` login-də bir dəfə). Ehtiyat-admin HEÇ BİR flag
        daşımadığı üçün flag-əsaslı menyu qapısı onu ekrana buraxmırdı; reyestr
        üzvlüyü isə DATA-dır, flag deyil. HƏR ƏMƏLİYYATIN faktiki qapısı use
        case-in ÖZÜNDƏ QALIR (`request_access`, `approve` — bax yuxarı);
        görünmə əməliyyat icazəsi DEYİL (bax `menu.py` başlığı).
        """
        return self._grants.find_trustee(tenant_id, employee_id) is not None

    def may_manage(self, *, tenant_id: TenantId, actor: Employee) -> bool:
        """Reyestr İDARƏETMƏSİnin görünürlük sualı (`trustees` ilə EYNİ qapı).

        GUI sətirlərinə «Dayandır/Ləğv Et» düyməsinin çəkilməsi üçündür —
        faktiki qapılar metodların özlərindədir. AYRI sabit YOXDUR: qapı
        `MANAGE_BREAK_GLASS_FLAG`-dır və burada da ONDAN oxunur, ikinci yazılış
        iki qaydanın ayrılması demək olardı.
        """
        return actor.has_permission(MANAGE_BREAK_GLASS_FLAG, now=self._clock.now())

    def open_grant_for(
        self, tenant_id: TenantId, employee_id: EmployeeId
    ) -> BreakGlassGrant | None:
        """İşçinin açıq (gözləyən və ya aktiv) sorğusu — ÖZ status kartı üçün.

        Səlahiyyət yoxlaması YOXDUR və bu QƏSDLİDİR: işçi YALNIZ öz sətrini
        oxuyur ("öz məlumatını görmək" qaydası, `menu.py` başlığı) — başqasının
        sətri bu metoddan KEÇMİR, siyahılar `pending_inbox`/`active_grants`
        ilə ayrıca qapılanır.
        """
        return self._grants.find_open_for_employee(tenant_id, employee_id)

    def active_grants(self, *, tenant_id: TenantId, actor: Employee) -> list[BreakGlassGrant]:
        """Qüvvədə olan fövqəladə səlahiyyətlər — təsdiqləyici görür.

        Təsdiqləyicinin BUNU GÖRMƏSİ MÜDAFİƏDİR: «hazırda kimin fövqəladə
        səlahiyyəti var?» sualı Root-un yox, ikinci-etibarlı şəxsin də sualıdır
        — o, verdiyi təsdiqin hələ də qüvvədə olub-olmadığını bilməlidir.
        LƏĞV ETMƏK ayrıca `revoke`-dadır və o, `can_manage_break_glass`
        (yalnız Root) tələb edir.
        """
        self._require_approver(tenant_id, actor)
        return self._grants.list_active(tenant_id)

    # ---------------------------- PLANLAYICI --------------------------------- #

    def expire_due(self, *, tenant_id: TenantId) -> int:
        """Vaxtı keçmiş sorğuları/səlahiyyətləri bağlayır. Qaytarır: neçə sətir.

        İKİ NÖV KEÇMƏ: təsdiq pəncərəsi (`PENDING_APPROVAL`) və səlahiyyət
        müddəti (`ACTIVE`). İkisi eyni dövrədə emal olunur, çünki hər ikisi
        eyni sualın («bu sətir hələ canlıdırmı?») cavabıdır və ayrı işlərə
        bölünsəydi biri qeydiyyatdan düşməklə sükutla ölə bilərdi
        (`composition.py`-nin sənədləşdirdiyi «yazılıb, çağıran yoxdur»
        boşluğu).
        """
        now = self._clock.now()
        closed = 0
        for grant in self._grants.list_pending(tenant_id):
            if grant.expire_if_unapproved(moment=now):
                self._grants.save_grant(grant)
                self._record_expiry(tenant_id, grant, kind="APPROVAL_WINDOW")
                closed += 1
        for grant in self._grants.list_active(tenant_id):
            if grant.expire_if_elapsed(moment=now):
                self._grants.save_grant(grant)
                self._record_expiry(tenant_id, grant, kind="DURATION")
                self._notifier.notify(
                    tenant_id=tenant_id,
                    recipient_id=grant.requested_by,
                    category="BREAK_GLASS_DECIDED",
                    title_az="Fövqəladə səlahiyyətin müddəti bitdi",
                    body_az=(
                        "Müvəqqəti Root səlahiyyətiniz bitdi. Lazım olarsa yeni sorğu göndərin."
                    ),
                    is_critical=False,
                )
                closed += 1
        return closed

    def retry_vendor_reports(self, *, tenant_id: TenantId) -> int:
        """Vendor bazasına çatmamış sətirləri yenidən göndərir. Qaytarır: uğurlu say."""
        if self._vendor is None:
            return 0
        sent = 0
        for grant in self._grants.list_vendor_unsynced(tenant_id, limit=VENDOR_RETRY_BATCH):
            # GÖZLƏYƏN SORĞU GÖNDƏRİLMİR: o hələ heç bir səlahiyyət vermir və
            # ölə bilər. Yalnız QƏRARA BAĞLANMIŞ sətirlər vendor üçün fakt
            # daşıyır.
            if grant.status is BreakGlassStatus.PENDING_APPROVAL:
                continue
            if self._report_to_vendor(grant):
                sent += 1
        return sent

    # ------------------------------- DAXİLİ ---------------------------------- #

    def _report_to_vendor(self, grant: BreakGlassGrant) -> bool:
        """Mərkəzi vendor bazasına bildirir. Uğursuzluq ƏMƏLİYYATI POZMUR."""
        if self._vendor is None or grant.vendor_synced_at is not None:
            return False
        delivered = self._vendor.report(grant)
        if not delivered:
            _security_log.warning(
                "BREAK_GLASS_VENDOR_REPORT_FAILED",
                extra={"grant_id": str(grant.id)},
            )
            return False
        grant.mark_vendor_synced(synced_at=self._clock.now())
        self._grants.save_grant(grant)
        return True

    def _record_expiry(self, tenant_id: TenantId, grant: BreakGlassGrant, *, kind: str) -> None:
        self._audit.record(
            tenant_id=tenant_id,
            # PLANLAYICI İNSAN DEYİL: `actor_id=None` — `ExceptionRaisedEvent`
            # ilə eyni qərar (bax `events/__init__.py` şərhi).
            actor_id=None,
            action="BREAK_GLASS_EXPIRED",
            entity_type="break_glass_grants",
            entity_id=grant.id,
            after_state={"status": grant.status.value, "expiry_kind": kind},
        )

    def _require_monthly_quota(self, tenant_id: TenantId, *, now: datetime) -> None:
        """Aylıq tavan — TƏQVİM ayı deyil, SÜRÜŞƏN 30 gün.

        Təqvim ayı seçilsəydi, ayın son günü iki, növbəti günü daha iki sorğu
        mümkün olardı — yəni 48 saatda tavanın iki qatı. Sürüşən pəncərə bu
        sərhəd oyununu bağlayır (`SELF_CORRECTION_REQUEST_WINDOW_DAYS`-in
        eyni qərarı).
        """
        cap = limit_int(self._limits, tenant_id, SystemLimitKey.BREAK_GLASS_MAX_GRANTS_PER_MONTH)
        used = self._grants.count_since(tenant_id, since=now - timedelta(days=30))
        if used >= cap:
            _security_log.warning(
                "BREAK_GLASS_QUOTA_EXCEEDED",
                extra={"tenant_id": str(tenant_id), "used": used, "cap": cap},
            )
            raise BreakGlassError(
                "Aylıq fövqəladə giriş həddi doldu",
                user_message=(
                    f"Son 30 gündə {used} fövqəladə giriş sorğusu olub (hədd: {cap}). "
                    "Root ilə birbaşa əlaqə saxlayın."
                ),
                context={"used": used, "cap": cap},
            )

    def _require_grant(
        self, tenant_id: TenantId, grant_id: BreakGlassGrantId, *, expect_pending: bool = True
    ) -> BreakGlassGrant:
        grant = self._grants.get_grant(grant_id)
        if grant is None or grant.tenant_id != tenant_id:
            raise BreakGlassNotFoundError(
                "Fövqəladə giriş sorğusu tapılmadı",
                context={"grant_id": str(grant_id)},
            )
        if expect_pending and not grant.is_pending:
            raise BreakGlassError(
                "Sorğu artıq qərara bağlanıb",
                user_message="Bu sorğu artıq cavablandırılıb.",
                context={"status": grant.status.value},
            )
        return grant

    def _require_approver(self, tenant_id: TenantId, actor: Employee) -> None:
        """Təsdiqləyici ya flag daşıyır, ya da AKTİV ehtiyat-admindir.

        İKİNCİ YOL QƏSDLİDİR: Root DA, CEO DA əlçatmaz ola bilər (eyni
        hadisə — məs. şirkət səfərdə). Belə halda iki ehtiyat-admin
        bir-birini təsdiqləyir. «İki nəfər» zəmanəti POZULMUR (özünü təsdiq
        həm DB-də, həm domendə qadağandır), yalnız kimlərin ikinci nəfər ola
        biləcəyi genişlənir — və hər belə təsdiq eyni audit sətrinə düşür.
        """
        if actor.has_permission(APPROVE_BREAK_GLASS_FLAG, now=self._clock.now()):
            return
        if self._grants.find_trustee(tenant_id, actor.id) is not None:
            return
        raise BreakGlassPermissionError(
            "Fövqəladə girişi təsdiqləmək üçün səlahiyyət yoxdur",
            context={"actor_id": str(actor.id)},
        )

    def _require(self, actor: Employee, flag: str) -> None:
        if not actor.has_permission(flag, now=self._clock.now()):
            raise BreakGlassPermissionError(
                f"«{flag}» səlahiyyəti tələb olunur",
                context={"actor_id": str(actor.id), "flag": flag},
            )
