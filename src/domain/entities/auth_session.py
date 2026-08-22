"""Admin/Kamera sessiyasının müddət idarəsi (SEC-011) — Dövrə debatı, SEC-5.

──────────────────────────────────────────────────────────────────────────────
NİYƏ TAPILDI: SƏNƏD "QORUNUB" DEYİRDİ, KOD HEÇ NƏ YAZMIRDI
──────────────────────────────────────────────────────────────────────────────
`docs/security_decisions.md` SEC-011 "Tətbiq: schema.sql §17b" yazırdı, lakin
`auth_sessions` cədvəli tətbiq tərəfindən HEÇ VAXT yazılmır/oxunmurdu —
`profile.py`-dakı sessiya siyahısı isə cədvəldən oxuyurdu, yəni istifadəçiyə
HƏMİŞƏ boş siyahı göstərilirdi. Sənəd real qorumanın olduğunu iddia edirdi,
qoruma faktiki YOX idi. Bu fayl həmin boşluğu bağlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `AggregateRoot` DEYİL — HADİSƏ YAYMIR
──────────────────────────────────────────────────────────────────────────────
`PinSecurityState` (`entities/employee.py`) ilə EYNİ qərar: sessiya heç bir
digər aqreqatla koordinasiya olunmur (Saga tələb etmir) və heç bir dinləyici
onun hadisəsini gözləmir — yeganə tələb DB audit sətridir (`AuditTrail`,
use case səviyyəsində), Event Bus deyil. Süni `record_event()` çağırışı bu
layihənin "5 `_drain()` halı" səhvini (dövrə 1 debatı, D2) təkrarlayardı:
heç bir dinləyicisi olmayan hadisə yaratmaq.

──────────────────────────────────────────────────────────────────────────────
`absolute_expiry` NİYƏ ENTITY-DƏ QORUNUR, USE CASE-DƏ YOX
──────────────────────────────────────────────────────────────────────────────
SEC-011-in bütün mənası budur: hərəkətsizlik pəncərəsi UZANA bilər (istifadəçi
işləyir), MÜTLƏQ tavan İSƏ HEÇ VAXT. `touch()` bunu `min(namizəd,
absolute_expiry)` ilə RİYAZİ olaraq mümkünsüz edir — use case səviyyəsində
"unutma" ilə pozula bilən bir `if` şərti DEYİL, entity-nin özü bu vəziyyətə
keçə BİLMİR (bax `LeaveRequest.verify_return` başlığındakı eyni fəlsəfə:
"hansı use case çağırmasından asılı olmamalıdır").

DB-dəki `chk_session_expiry CHECK (expires_at <= absolute_expiry)` bunun
İKİNCİ qatıdır (CLAUDE.md §5: hər qayda iki yerdə).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.value_objects.scheduling import require_aware
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from src.domain.value_objects.identifiers import EmployeeId, SessionId, TenantId


class SessionContext(str, Enum):
    """`auth_sessions.context` `CHECK`-i ilə EYNİ üç dəyər (schema.sql §17b).

    `KIOSK` bu use case-dən sessiya ALMIR (SEC-011: "hər əməliyyat üçün PIN,
    sessiya yoxdur") — dəyər yalnız DB `CHECK`-i ilə paritet üçün burada
    saxlanılır, `SessionManagementUseCase.issue()` ona limit axtarmır.
    """

    ADMIN_PANEL = "ADMIN_PANEL"
    CAMERA_DASHBOARD = "CAMERA_DASHBOARD"
    KIOSK = "KIOSK"

    @property
    def has_idle_timeout(self) -> bool:
        """Hərəkətsizlik pəncərəsi bu kontekstə aiddirmi.

        `CAMERA_DASHBOARD`-da YOX: operator ekrana BAXIR, klikləmir — SEC-011-in
        açıq tələbi. Yalnız mütləq tavan (`absolute_expiry`) qüvvədədir.
        """
        return self is SessionContext.ADMIN_PANEL


@dataclass
class AuthSession:
    """`auth_sessions` sətrinin domen güzgüsü.

    Açıq token (`secrets.token_urlsafe(32)`) BURADA SAXLANMIR — yalnız
    `token_hash` (SHA-256). Açıq token GUI yaddaşında yaşayır, `issue()`-nin
    qaytardığı BİR DƏFƏLİK dəyərdir (bax `authentication.py`).
    """

    id: SessionId
    tenant_id: TenantId
    user_id: EmployeeId
    token_hash: str
    context: SessionContext
    issued_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    absolute_expiry: datetime
    revoked_at: datetime | None = None
    revoked_by: EmployeeId | None = None
    revocation_reason: str | None = None
    machine_name: str | None = None
    ip_address: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.issued_at, field="issued_at")
        require_aware(self.expires_at, field="expires_at")
        require_aware(self.last_seen_at, field="last_seen_at")
        require_aware(self.absolute_expiry, field="absolute_expiry")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, field="revoked_at")
        if self.expires_at > self.absolute_expiry:
            # `chk_session_expiry`-nin domendəki əksi — DB-yə çatmadan tutulur.
            raise DomainRuleError(
                "Sessiyanın hərəkətsizlik həddi mütləq həddi keçə bilməz",
                context={
                    "expires_at": self.expires_at.isoformat(),
                    "absolute_expiry": self.absolute_expiry.isoformat(),
                },
            )

    # ------------------------------ sorğular --------------------------------- #

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_valid(self, *, now: datetime) -> bool:
        """Sessiya bu an ETİBARLIDIRMI (ləğv edilməyib, iki müddət də keçməyib)."""
        require_aware(now, field="now")
        if self.is_revoked:
            return False
        if now >= self.absolute_expiry:
            return False
        return not now >= self.expires_at

    # ------------------------------ keçidlər ---------------------------------- #

    def touch(self, *, now: datetime, idle_timeout: timedelta) -> None:
        """Hərəkətsizlik pəncərəsini UZADIR — `absolute_expiry`-ni ƏSLA UZATMIR.

        `context.has_idle_timeout` `False`-dursa (bax `CAMERA_DASHBOARD`)
        SÜKUTLA HEÇ NƏ ETMİR — bu, səlahiyyət yoxlaması deyil (istisna atacaq
        bir "pozuntu" yoxdur), sadəcə həmin kontekstdə əməliyyat MƏNASIZDIR:
        `BreakUsage.record_use`-un sistem-olmayan icazə növündə `None`
        qaytarması ilə EYNİ naxış — çağıran tərəf hər halda nəticəni yoxlamır.
        """
        require_aware(now, field="now")
        if self.is_revoked:
            raise InvalidStateTransitionError(
                "Ləğv edilmiş sessiya uzadıla bilməz",
                context={"session_id": str(self.id)},
            )
        if not self.context.has_idle_timeout:
            return
        self.last_seen_at = now
        # KRİTİK SƏTİR — SEC-011-in BÜTÜN MƏNASI: namizəd `absolute_expiry`-ni
        # keçə bilmir, çünki `min()` onu RİYAZİ olaraq bağlayır. Bu sətri
        # `self.expires_at = now + idle_timeout` ilə əvəz etmək gecə növbəsinə
        # QALAN açıq sessiya yaradardı — məhz SEC-011-in qadağan etdiyi hal.
        self.expires_at = min(now + idle_timeout, self.absolute_expiry)

    def revoke(self, *, revoked_by: EmployeeId | None, reason: str, now: datetime) -> None:
        """Sessiyanı ləğv edir — özü tərəfindən (çıxış) və ya admin tərəfindən.

        İDEMPOTENTDİR: artıq ləğv edilmiş sessiyada TƏKRAR çağırış səssizcə
        keçilir — "kim əvvəl bağladı" yarışı (özü çıxış edib, admin də eyni
        anda ləğv edib) istisna ilə uğursuz olmamalıdır, nəticə eynidir.
        """
        require_aware(now, field="now")
        if self.is_revoked:
            return
        self.revoked_at = now
        self.revoked_by = revoked_by
        self.revocation_reason = normalise_decision_text(reason) or "Səbəb göstərilmədi"


__all__ = ["AuthSession", "SessionContext"]
