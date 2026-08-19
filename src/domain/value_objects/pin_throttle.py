"""Terminal-səviyyəli PIN throttle vəziyyəti (SEC-01/SEC-05, dövrə 3-4 audit).

──────────────────────────────────────────────────────────────────────────────
NİYƏ İŞÇİ-BAŞINA `PinSecurityState`-DƏN AYRI, TERMİNAL-SƏVİYYƏLİ QAT LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
`PinSecurityState` (`entities/employee.py`) VƏ ona bağlı `PinHandshakeUseCase.
register_failure()` İŞÇİ-BAŞINA lockout tərtib edir — dövrə 1 auditinin (SEC-01)
tapdığı kimi, bu, kiosk PIN axınında PRİNSİPCƏ ƏLÇATMAZDIR: PIN ANONİMDİR,
`PinHandshakeUseCase.authenticate()` mağazadakı BÜTÜN namizədləri sınayır və
heç biri uyğun gəlmədikdə HANSI işçinin cəhd etdiyini BİLMİR (bax
`group_a_kiosk.py:364`). Nəticədə `register_failure()` canlı axından HEÇ VAXT
çağırıla bilmir. Bu fayl HƏMİN boşluğu BAĞLAMIR (`PinSecurityState` SİLİNMİR —
bax onun öz faylındakı şərh), ƏVƏZİNƏ İKİNCİ, MÜSTƏQİL bir qat əlavə edir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `store_id` DEYİL, `MachineIdentityHash` — AÇAR DƏYİŞİKLİYİ (SEC-05)
──────────────────────────────────────────────────────────────────────────────
İlk versiya `(tenant_id, store_id)` açarı işlədirdi. `security` bunu kod
yazılmamışdan ƏVVƏL sındırdı: `store_id` `KOMPASOS_STORE_ID` mühit
dəyişənindən gəlir və admin hüququ OLMADAN dəyişdirilə bilər (`HKCU\\
Environment`) — throttle-ı HEÇ VAXT işə düşməyəcək şəkildə yan keçmək mümkün
olardı. `MachineIdentityHash` (`value_objects/machine_identity.py`) əvəzinə
işlədilir — bax onun öz modul başlığı.

`store_id` BURADA sətrin MƏLUMAT sahəsi kimi QALIR (açarın hissəsi DEYİL) —
son görülən mağazanı izləyir və klon-aşkarlamasının (bax `PinHandshakeUseCase`-
in "KLON AŞKARLAMASI" bölməsi) mənbəyidir.

──────────────────────────────────────────────────────────────────────────────
SABİT-PƏNCƏRƏ MODELİ VƏ `advance_after_failure` — TƏK MƏNBƏ (dövrə 4 düzəlişi)
──────────────────────────────────────────────────────────────────────────────
İLK versiyada pəncərə/kilid arifmetikası TAMAMİLƏ DB trigger-ində idi və
domen `window_started_at`-ı belə görmürdü. Bu, YANLIŞ VƏ TƏHLÜKƏLİ çıxdı:
`security`/`qa` "uğurda sıfırlama yoxdur" qərarını (aşağı) TƏK BAŞINA
tətbiq etsəydi, sayğac 20-yə çatandan sonra HEÇ VAXT geri dönməzdi — kilid
15 dəqiqədən sonra bitər, AMMA sonrakı İLK uğursuz cəhd sayğacı 21 edib
terminalı DƏRHAL YENİDƏN kilidləyər — ƏBƏDİ kilid.

Həll: `advance_after_failure()` SABİT-PƏNCƏRƏ modelini TƏTBİQ EDİR —
`window_started_at` KEÇMİŞ pəncərənin başlanğıcını saxlayır, pəncərə
(`KIOSK_STORE_PIN_LOCKOUT_MINUTES`) bitəndə YENİ pəncərə `failed_count=1`-
dən başlayır. Bu metod TƏK MƏNBƏDİR (`is_locked()`-in EYNİ `now < locked_until`
sərhədini YENİDƏN yazmır, ÇAĞIRIR) — iki YERDƏ (bu fayl və gələcək SQL
trigger) fərqli sərhəd yazılıb "bir anlıq" (`now == locked_until`) fərqli
nəticə verməsin deyə (team-lead-in "iki metoddan gizli sərhəd fərqi
qalmasın" tələbi).

Bu, HƏLƏ DƏ real istehsalat yolunda DB TRİGGER-İN İŞLƏTDİYİ SQL DEYİL (TIME-1:
server-vaxtına bağlı hesablama client-in çağırdığı Python-dan ASILI OLA
BİLMƏZ — infra `system_limits`-i BİRBAŞA SQL-dən oxuyur). `advance_after_
failure()` İKİ məqsədə xidmət edir: (1) sınaq sahtəsinin (`InMemoryPinThrottle`,
`tests/fixtures/fakes.py`) İCRA ETDİYİ İCRAÇI SPESİFİKASİYA — semantika BİR
YERDƏ yazılır, sahtə onu YENİDƏN İCAD ETMİR; (2) infra-nın SQL trigger-inin
UYĞUNLAŞMALI OLDUĞU YAZILI QƏRAR (CLAUDE.md §7-nin "sütun yox, qayda
dəyişirsə hər iki yer" prinsipi — burada "hər iki yer" Python spesifikasiyası
VƏ SQL trigger-idir).

──────────────────────────────────────────────────────────────────────────────
UĞURLU GİRİŞ SAYĞACA TOXUNMUR (SEC-05, ARCHITECT-security debatı)
──────────────────────────────────────────────────────────────────────────────
Bu faylda "reset" metodu QƏSDƏN YOXDUR: sıfırlama olsaydı, hücumçu hədd-1
səhv edib paylaşılan terminalın NÖVBƏTİ qanuni girişini gözləməklə sayğacı
PULSUZ təmizləyərdi (kənar hücumçuya "öz" uğurlu girişi lazım DEYİL, başqasının
kifayətdir). Decay YALNIZ pəncərənin BİTMƏSİ ilə gəlir (yuxarı), uğurla YOX —
bu, İŞÇİ-səviyyəli `PinSecurityState`-dən (uğurda sıfırlanır) FƏRQİDİR: orada
HƏMİN ŞƏXS öz kimliyini sübut edir, burada isə BAŞQASININ sübutu aqreqat
sayğacı sıfırlaya BİLMƏZ.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SADƏ DƏYƏR OBYEKTİDİR — `AggregateRoot` DEYİL
──────────────────────────────────────────────────────────────────────────────
`AuthSession` (`entities/auth_session.py`) ilə EYNİ qərar: heç bir digər
aqreqatla koordinasiya olunmur, heç bir dinləyici hadisəsini gözləmir.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

from src.domain.entities.base import DomainRuleError
from src.domain.value_objects.scheduling import require_aware

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import StoreId, TenantId
    from src.domain.value_objects.machine_identity import MachineIdentityHash


@dataclass(frozen=True)
class TerminalPinThrottle:
    """`store_pin_throttle` sətrinin domen güzgüsü (SEC-01/SEC-05, dövrə 3-4).

    `store_id`: sətrə YAZILAN SON mağaza — açar DEYİL, klon-aşkarlamasının
    müqayisə etdiyi dəyər. Sətir hələ HEÇ yazılmayıbsa (`get_for_update`
    `None` qaytarır) müqayisə ediləcək əvvəlki dəyər YOXDUR.

    `window_started_at`: cari sabit-pəncərənin başlanğıcı. `None` = HƏLƏ
    heç bir pəncərə açılmayıb (bu maşında ilk uğursuz cəhd hələ gəlməyib).
    """

    tenant_id: TenantId
    machine_key: MachineIdentityHash
    store_id: StoreId
    failed_count: int
    window_started_at: datetime | None
    locked_until: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.updated_at, field="updated_at")
        if self.window_started_at is not None:
            require_aware(self.window_started_at, field="window_started_at")
        if self.locked_until is not None:
            require_aware(self.locked_until, field="locked_until")
        if self.failed_count < 0:
            raise DomainRuleError(
                "Terminal PIN səhv sayğacı mənfi ola bilməz",
                context={"failed_count": self.failed_count},
            )

    def is_locked(self, *, now: datetime) -> bool:
        """Terminal BU AN bloklanıbmı.

        SƏRHƏD `now < locked_until` — QƏTİDİR (`<`, `<=` DEYİL): dəqiq
        `now == locked_until` anında kilid ARTIQ BİTİB sayılır. Bu funksiya
        `advance_after_failure()`-in "pəncərə bitibmi?" sualının BİR
        HİSSƏSİDİR — sərhəd BURADA TƏK yerdə təyin olunur (aşağıya bax).
        """
        require_aware(now, field="now")
        return self.locked_until is not None and now < self.locked_until

    def advance_after_failure(
        self, *, now: datetime, max_attempts: int, lockout_minutes: int
    ) -> TerminalPinThrottle:
        """Anonim uğursuz PIN cəhdindən SONRAKI vəziyyəti hesablayır (dövrə 4).

        Sabit-pəncərə modeli — bax fayl başlığı. Bu metod PYTHON-DA ÇAĞIRILAN
        istehsalat kodu DEYİL (real yol DB trigger-idir, TIME-1) — o, sınaq
        sahtəsinin (`InMemoryPinThrottle`) icra etdiyi İCRA OLUNAN
        SPESİFİKASİYADIR, ona görə YAN TƏSİRSİZDİR (yeni `TerminalPinThrottle`
        qaytarır, `self`-i DƏYİŞMİR).

        Qaydalar:
          1. Terminal BU AN kilidlidirsə (`is_locked(now=now)`), sayğac DONUR
             — dəyişmədən `self` qaytarılır. Normal axında BURAYA ÇATILMIR
             (`PinHandshakeUseCase._require_unlocked_throttle` əvvəlcədən
             yoxlayıb), amma müdafiə xətti kimi saxlanılır: kilid MÜDDƏTİ
             TƏKRAR uzadıla bilməz.
          2. Əks halda: pəncərə bitibmi yoxlanır — `window_started_at` yoxdur,
             VƏ YA `now - window_started_at >= lockout_minutes`, VƏ YA
             `locked_until` DOLUDUR (bu nöqtədə `is_locked` artıq `False`
             olduğu üçün bu, "kilid keçib" deməkdir — TƏKRAR `now >=
             locked_until` yazılmır, addım 1-in nəticəsindən İSTİFADƏ olunur).
          3. Pəncərə bitibsə: YENİ pəncərə başlayır (`failed_count=1`,
             `window_started_at=now`). Bitməyibsə: `failed_count += 1`,
             `window_started_at` DƏYİŞMİR.
          4. `failed_count >= max_attempts`-dirsə YENİ kilid qoyulur
             (`now + lockout_minutes`), əks halda `locked_until = None`.
        """
        require_aware(now, field="now")
        if self.is_locked(now=now):
            return self

        window_duration = timedelta(minutes=lockout_minutes)
        window_expired = (
            self.window_started_at is None
            or now - self.window_started_at >= window_duration
            or self.locked_until is not None
        )
        window_started_at: datetime
        if window_expired:
            failed_count = 1
            window_started_at = now
        else:
            failed_count = self.failed_count + 1
            # `window_expired`-in birinci şərti (`window_started_at is None`)
            # burada `False`-dur, ona görə dəyər HƏMİŞƏ doludur — mypy-a
            # bunu açıq bildiririk (runtime təhlükəsizdir).
            assert self.window_started_at is not None
            window_started_at = self.window_started_at

        locked_until = now + window_duration if failed_count >= max_attempts else None
        return replace(
            self,
            failed_count=failed_count,
            window_started_at=window_started_at,
            locked_until=locked_until,
            updated_at=now,
        )


__all__ = ["TerminalPinThrottle"]
