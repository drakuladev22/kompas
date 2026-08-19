"""Terminalın aparat kimliyinin HASH-lanmış açarı (SEC-01/SEC-05, dövrə 3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `store_id` DEYİL — SEC-05 AUDİT TAPINTISI
──────────────────────────────────────────────────────────────────────────────
İlk dizaynda terminal PIN throttle-ı `(tenant_id, store_id)` açarı ilə
saxlanılırdı. `security` bunu kod yazılmamışdan ƏVVƏL sındırdı: `store_id`
YALNIZ `KOMPASOS_STORE_ID` mühit dəyişənindən gəlir (`app.py:4016`), istehsalat
paketlənməsində `.env` qadağan olduğu üçün dəyər `HKCU\\Environment`-dədir —
BU, ADMİN HÜQUQU TƏLƏB ETMİR. Hücumçu throttle həddinə yaxınlaşanda dəyişəni
dəyişib TƏZƏ sayğac ala bilərdi — qoruma HEÇ VAXT işə düşməzdi.

Əvəzinə `MachineGuid` (Windows quraşdırma GUID-i, `HKEY_LOCAL_MACHINE`)
işlədilir: bu, ADMİN HÜQUQU olmadan dəyişdirilə BİLMƏZ (`device_identity.py`
`security`-nin faylıdır, oxu-heşləmə ORADA aparılır — bax aşağıdakı bənd).

──────────────────────────────────────────────────────────────────────────────
NİYƏ XAM GUID DEYİL, HEŞ
──────────────────────────────────────────────────────────────────────────────
Domen/tətbiq qatı `winreg` idxal ETMİR (CLAUDE.md §3: `domain/` heç vaxt OS-a
xas modul idxal etmir) — GUID-i OXUMAQ İNFRASTRUKTUR işidir (`Clock`/
`ServerTimeService` ilə eyni prinsip: domen `datetime.now()` çağırmır, ONA
ÖTÜRÜLƏN dəyərlə işləyir). HEŞLƏMƏ də ORADA aparılır — domen qatına xam
aparat identifikatoru heç vaxt ÇATMIR, yalnız bu opaq SHA-256 dəyəri.

──────────────────────────────────────────────────────────────────────────────
KLON RİSKİ QƏBUL EDİLİR — SÜKUTLA YOX (TEAM-LEAD-İN ƏLAVƏ TAPŞIRIĞI)
──────────────────────────────────────────────────────────────────────────────
Sysprep edilməmiş klon disk imicində N maşın EYNİ `MachineGuid`-i daşıya
bilər — bu, `MachineIdentityHash`-in ÖZÜNÜN zəiflik NÖQTƏSİDİR, sükutla
qəbul edilir, çünki alternativ (heç bir maşın-səviyyəli açar) SEC-05-in
sındırdığı boşluğu geri gətirərdi. Kompensasiya: `PinHandshakeUseCase`
saxlanmış `store_id`-in dəyişməsini `security_events`-ə yazır (bax
`authentication.py`, "KLON AŞKARLAMASI" bölməsi) — bloklamır, YALNIZ iz
buraxır.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.shared.exceptions import KompasOSError

#: SHA-256 hex-digest uzunluğu — heş formatının yeganə etibarlılıq şərtidir.
_SHA256_HEX_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


class InvalidMachineIdentityError(KompasOSError):
    """Ötürülən dəyər SHA-256 hex-digest formatında deyil."""

    user_message = "Terminal kimliyi oxuna bilmədi."


@dataclass(frozen=True)
class MachineIdentityHash:
    """Windows `MachineGuid`-in SHA-256 heşi — terminal PIN throttle açarı.

    `digest` HƏMİŞƏ kiçik hərflə normallaşdırılır ki, eyni GUID-dən gələn
    heş TUTARLI açar versin (heş funksiyasının özü artıq case-sensitiv
    DEYİL, amma çağıran tərəf format fərqli ötürə bilər).
    """

    digest: str

    def __post_init__(self) -> None:
        cleaned = self.digest.strip().lower()
        if len(cleaned) != _SHA256_HEX_LENGTH or any(c not in _HEX_DIGITS for c in cleaned):
            raise InvalidMachineIdentityError(
                "Maşın kimliyi SHA-256 hex-digest formatında olmalıdır (64 simvol)",
                context={"length": len(cleaned)},
            )
        object.__setattr__(self, "digest", cleaned)


__all__ = ["InvalidMachineIdentityError", "MachineIdentityHash"]
