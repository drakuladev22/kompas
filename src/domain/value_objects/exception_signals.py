"""Vahid İstisna Motorunun domen tipləri (#9) — Faza 3.

Bu modul motorun DİLİNİ təyin edir: qayda nə qaytarır (`ExceptionFinding`),
qayda hansı kontekstlə işləyir (`RuleEvaluationContext`), mənbə kataloqu nə
verir (`ExceptionSource`) və ciddiyyət/status hansı dəyərləri ala bilər.

──────────────────────────────────────────────────────────────────────────────
NİYƏ QAYDA `ExceptionRecord` DEYİL, `ExceptionFinding` QAYTARIR
──────────────────────────────────────────────────────────────────────────────
Qayda "bu işçidə bu anomaliya var" deyir — SƏTRİ isə motor yaradır. Fərq
xırda görünür, amma üç şeyi struktur olaraq həll edir:

  1. **Kimlik motorundadır.** `ExceptionId`, `created_at` və mənbə kodunun
     kataloqla uyğunluğu bir yerdə verilir. Qayda öz `id`-sini yaratsaydı,
     iki qayda eyni sətri iki fərqli identifikatorla yarada bilərdi.
  2. **Ciddiyyət ROOT-dan gəlir.** Qayda `severity=None` qaytara bilər və
     motor onu `exception_sources.default_severity` ilə doldurur — yəni
     ciddiyyəti dəyişmək üçün YENİ BURAXILIŞ lazım deyil (migrations/018
     bu sütunu məhz bunun üçün əlavə edib).
  3. **Qayda saxlama qatını tanımır.** `ExceptionFinding` sadə dəyər
     obyektidir: qaydanın testi repo, tranzaksiya və audit olmadan yazılır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ KONTEKST `SystemLimits` PORTUNU YOX, HAZIR SNAPSHOT DAŞIYIR
──────────────────────────────────────────────────────────────────────────────
`RuleEvaluationContext.limits` — `system_limits`-in bir icra üçün oxunmuş
NÜSXƏSİDİR (`SystemLimits.all_for()`). Portun özünü daşımaq iki problem
yaradardı:

  * `value_objects` → `interfaces.ports` idxalı DÖVRƏ verərdi (ports.py bu
    modulu idxal edir);
  * hər qayda öz limitini ayrıca oxuyardı və uzun icra ərzində Root dəyəri
    dəyişsəydi, EYNİ gecənin tapıntıları müxtəlif həddlərlə hesablanardı.

Snapshot hər iki problemi bağlayır və `LeaveAllowancePolicy.from_limits()`
naxışını təkrarlayır (o da lüğət alır, port yox).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Final

from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId
from src.domain.value_objects.scheduling import require_aware

#: Bu partiyanın YEGANƏ mənbə kodu (kompasos11.md struktur qərarı B,
#: migrations/018 seed-i). Sabit burada elan olunur ki, Faza 5-in qaydası və
#: ekran mətni eyni sətri İKİ yerdə yazmasın — `menu.py` başlığındakı
#: ikili-ad-məkanı qüsuru məhz belə yaranmışdı.
BEHAVIOR_ANOMALY_SOURCE: Final = "BEHAVIOR_ANOMALY"

#: Face Control-un mənbə kodu (`facecontrol.md` bənd 16, migrations/047 seed-i).
#: Sabit MƏHZ BURADA, `BEHAVIOR_ANOMALY_SOURCE` ilə YAN-YANA elan olunur ki,
#: qaydanın (`FaceMismatchExceptionRule.source_code`) yazdığı sətir ilə
#: kataloqdakı sətir arasında ikinci bir ad məkanı yaranmasın — `menu.py`
#: başlığındakı qüsur məhz belə doğulmuşdu. Motorun kodu bu sabiti TANIMIR:
#: mənbə seçimi reyestr vasitəsilə edilir, `if source == ...` zənciri yoxdur.
FACE_MISMATCH_SOURCE: Final = "FACE_MISMATCH"

#: HR-1/HR-2/HR-3 — cərimə axınının ÜÇ dayanma nöqtəsi (DEEP-GAP).
#:
#: Sabitlər `BEHAVIOR_ANOMALY_SOURCE`/`FACE_MISMATCH_SOURCE` ilə YAN-YANA
#: durur və eyni səbəbdən: qaydanın yazdığı sətir ilə `exception_sources`
#: kataloqundakı sətir arasında İKİNCİ ad məkanı yaranmasın.
#:
#: ÜÇÜ NİYƏ AYRI MƏNBƏDİR (bir «FINE_STUCK» mənbəyi kifayət etməzdi): hər
#: birinin HƏLLİ FƏRQLİ ƏLDƏDİR — etiraza qərar verən `can_approve_leave_
#: appeal`, icmalı keçirən `can_publish_fines`, işdən çıxmış işçinin
#: cəriməsinə qərar verən isə HR-dır. Kataloq sətri ROOT tərəfindən ayrıca
#: söndürülə (`is_active`) və ayrıca ciddiyyət ala bilir; birləşdirilsəydi
#: bu üç qərar bir açara bağlanardı.
#: HR-1 — etiraz pəncərəsi bağlanıb, qərar HƏLƏ yoxdur.
FINE_APPEAL_UNANSWERED_SOURCE: Final = "FINE_APPEAL_UNANSWERED"
#: HR-2 — cərimə aylıq icmalda ilişib, işçi onu GÖRMÜR.
FINE_REVIEW_OVERDUE_SOURCE: Final = "FINE_REVIEW_OVERDUE"
#: HR-3 — işçi deaktivdir, cəriməsi isə nəşr gözləyir (`fine_review.py`
#: `held_inactive_employee` qolu). Nəşr STRUKTUR olaraq mümkün deyil, ona
#: görə sətir hər ay yenidən görünür və çıxış yolu YALNIZ insan qərarıdır.
FINE_HELD_INACTIVE_SOURCE: Final = "FINE_HELD_INACTIVE_EMPLOYEE"

#: UX-7 — möhlət bitib, işçinin üzü HƏLƏ qeydiyyatda deyil.
#:
#: `FACE_MISMATCH_SOURCE`-dan AYRIDIR və qarışdırılmamalıdır: o, «qeydiyyatlı
#: işçinin üzü uyğun gəlmədi» (təhlükə siqnalı), bu isə «qeydiyyat HEÇ VAXT
#: aparılmayıb» (proses boşluğu) deməkdir. Həlli də fərqlidir — birincisi
#: araşdırma, ikincisi sadəcə görüş təyin etmək.
FACE_ENROLLMENT_OVERDUE_SOURCE: Final = "FACE_ENROLLMENT_OVERDUE"

#: `exception_sources.code` üçün minimum uzunluq — DB `CHECK`-inin güzgüsü
#: (`char_length(trim(code)) >= 3`). Bu, biznes həddi DEYİL, sxem
#: məhdudiyyətidir; ona görə `system_limits`-ə aid deyil.
MIN_SOURCE_CODE_LENGTH: Final = 3


class ExceptionSeverity(str, Enum):
    """`exceptions.severity` — DB `CHECK` siyahısı ilə EYNİ.

    Siyahı SƏRTDİR (mənbə kataloqundan fərqli olaraq): yeni ciddiyyət dəyəri
    sıralama, rəng və bildiriş həddi kimi KOD davranışlarını dəyişir, yəni
    buraxılışsız mənası yoxdur (migrations/018 başlığı bunu izah edir).
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        """Müqayisə üçün sıra nömrəsi.

        `Enum` üzvləri arasında `<`/`>` işləmir və `str` müqayisəsi ƏLİFBA
        sırası verərdi ("CRITICAL" < "LOW"), yəni bildiriş həddi tam tərsinə
        işləyərdi. Ona görə sıra AÇIQ təyin olunur.
        """
        return _SEVERITY_RANK[self]

    def at_least(self, floor: ExceptionSeverity) -> bool:
        """Bu ciddiyyət verilmiş həddə çatırmı (bildiriş qapısı)."""
        return self.rank >= floor.rank

    @classmethod
    def parse(cls, raw: str | None, *, fallback: ExceptionSeverity) -> ExceptionSeverity:
        """Kənardan (DB/`system_limits`) gələn mətni dəyərə çevirir.

        Naməlum dəyər İSTİSNA ATMIR: Root sətri əl ilə redaktə edib yazı
        səhvi buraxsa, bütün gecəlik aşkarlama dayanardı. Fallback ilə motor
        işləməyə davam edir və səhv dəyər yalnız həmin parametri təsirsiz edir.
        """
        if raw is None:
            return fallback
        try:
            return cls(raw.strip().upper())
        except ValueError:
            return fallback


_SEVERITY_RANK: Final[dict[ExceptionSeverity, int]] = {
    ExceptionSeverity.LOW: 0,
    ExceptionSeverity.MEDIUM: 1,
    ExceptionSeverity.HIGH: 2,
    ExceptionSeverity.CRITICAL: 3,
}


class ExceptionStatus(str, Enum):
    """`exceptions.status` — iş axınının özü (OPEN → REVIEWED / DISMISSED).

    `DELETED` yoxdur və olmayacaq: rədd edilmiş istisna da "buna baxıldı və
    əsassız sayıldı" faktının sübutudur (migrations/018 `REVOKE DELETE`).
    """

    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    DISMISSED = "DISMISSED"

    @property
    def is_open(self) -> bool:
        return self is ExceptionStatus.OPEN


@dataclass(frozen=True)
class ExceptionSource:
    """`exception_sources` kataloq sətrinin domen görünüşü.

    Ad və izah BAZADAN gəlir, koddan yox — ekran ikinci ad məkanı qurmasın
    deyə (migrations/018, `name_az` şərhi).
    """

    code: str
    name_az: str
    description_az: str | None = None
    default_severity: ExceptionSeverity = ExceptionSeverity.MEDIUM
    is_active: bool = True


@dataclass(frozen=True)
class ExceptionFinding:
    """Bir qaydanın TƏK tapıntısı — hələ `exceptions` sətri DEYİL."""

    employee_id: EmployeeId
    store_id: StoreId
    detail: str
    #: Aşkarlamanın RƏQƏMLƏRİ (baz xətt, faktiki dəyər, kənarlaşma). Qara-qutu
    #: siqnal intizam qərarını əsaslandıra bilməz — `exceptions.context_json`.
    context: Mapping[str, object] = field(default_factory=dict)
    #: `None` = mənbənin `default_severity`-si tətbiq olunsun (ROOT-dan idarə).
    severity: ExceptionSeverity | None = None
    #: Təkrar-yaratma açarı (qayda + işçi + tarix). `None` verilərsə motor eyni
    #: tapıntını hər icrada YENİDƏN yaradar — planlaşdırılmış iş üçün açar
    #: praktiki olaraq məcburidir (bax `ExceptionEngineUseCase.run`).
    dedupe_key: str | None = None


@dataclass(frozen=True)
class RuleEvaluationContext:
    """Motorun bir icrası üçün qaydaya verilən kontekst.

    `as_of` `Clock` portundan gəlir — qayda `datetime.now()` ÇAĞIRMAMALIDIR,
    əks halda gecəlik aşkarlama determinstik test oluna bilməzdi.
    """

    tenant_id: TenantId
    as_of: datetime
    limits: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.as_of, field="as_of")

    def limit_int(self, key: str, default: int) -> int:
        """`system_limits`-dən tam ədəd — qaydanın həddləri üçün TƏK yol.

        Yararsız mətn (məs. boş sətir) defolta düşür: Root-un yazı səhvi
        aşkarlamanı çökdürməməlidir.
        """
        raw = self.limits.get(key)
        if raw is None:
            return default
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return default

    def limit_str(self, key: str, default: str) -> str:
        raw = self.limits.get(key)
        if raw is None or not str(raw).strip():
            return default
        return str(raw).strip()


__all__ = [
    "BEHAVIOR_ANOMALY_SOURCE",
    "FACE_ENROLLMENT_OVERDUE_SOURCE",
    "FACE_MISMATCH_SOURCE",
    "FINE_APPEAL_UNANSWERED_SOURCE",
    "FINE_HELD_INACTIVE_SOURCE",
    "FINE_REVIEW_OVERDUE_SOURCE",
    "MIN_SOURCE_CODE_LENGTH",
    "ExceptionFinding",
    "ExceptionSeverity",
    "ExceptionSource",
    "ExceptionStatus",
    "RuleEvaluationContext",
]
