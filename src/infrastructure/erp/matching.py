"""1C sənədinin işçi və mağazaya bağlanması (bölmə 6) — Faza 3.10.

Spesifikasiya: *"Əsas açar `(1C Unikal Satıcı ID + 1C Mağaza Kodu + Server
ID)` — mətn-əsaslı ad uyğunlaşdırması yalnız fallback kimi istifadə olunur.
Fallback nəticəsində uyğunlaşan hər sətir `LOW_CONFIDENCE_MATCH` işarəsi ilə
«Təyin Olunmamış / Şübhəli Uyğunlaşma» review queue-a düşür."*

──────────────────────────────────────────────────────────────────────────────
ARDICILLIQ
──────────────────────────────────────────────────────────────────────────────
    1. mağaza:  (server_id, one_c_store_code) → `store_server_mapping`
       tapılmasa → UNASSIGNED (işçini axtarmağın mənası yoxdur: eyni satıcı
       ID-si başqa serverdə başqa adamdır)
    2. işçi:    (store_id, one_c_seller_id)   → EXACT_MATCH
    3. fallback: ad oxşarlığı, YALNIZ həmin mağazanın işçiləri arasında
       → LOW_CONFIDENCE_MATCH
    4. heç biri → UNASSIGNED

──────────────────────────────────────────────────────────────────────────────
NİYƏ FALLBACK QƏSDƏN "KOR" DEYİL
──────────────────────────────────────────────────────────────────────────────
Ad müqayisəsi iki tələ daşıyır və hər ikisi PULA çevrilir:

    * TRANSLİTERASİYA: 1C-də "Aliyev Elvin", bizdə "Əliyev Elvin" — eyni
      adamdır, lakin bayt-bayt fərqlidir. Normalizasiya olmadan hər satış
      əl ilə təyin edilməli olardı.
    * QOHUM ADLAR: "Əliyev Elvin" ↔ "Əliyev Elnur" — FƏRQLİ adamlardır.
      Səhv uyğunlaşma bir işçinin satışını digərinin premiyasına yazır.

Ona görə: normalizasiya (transliterasiya + söz sırası) TƏTBİQ OLUNUR, lakin
hədd yüksəkdir və ƏN YAXŞI İKİ namizəd bir-birinə çox yaxındırsa nəticə
qəbul EDİLMİR — belə halda seçim insana buraxılır. "Bəlkə budur" deyib
təxmin etmək, boş buraxmaqdan bahalıdır.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.erp import (
    NAME_MATCH_THRESHOLD,
    MatchConfidence,
    MatchResult,
)
from src.infrastructure.config.limits import InfrastructureLimits, fallback_float
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.domain.value_objects.erp import OneCSaleRecord
    from src.domain.value_objects.identifiers import EmployeeId, ErpServerId, StoreId

_log = get_logger(__name__)

#: Azərbaycan diakritik hərflərinin sadə latın qarşılığı.
#:
#: `ə → a` (`e` YOX): 1C bazalarına adlar demək olar həmişə pasport/rus
#: sənədləşməsindən gəlir və orada "Əliyev" = "Алиев" = "Aliyev"-dir.
#: `e` seçilsəydi ən geniş yayılmış soyad qrupu (Ə ilə başlayanlar) heç vaxt
#: uyğunlaşmazdı. "Eliyev" kimi nadir yazılış isə cəmi bir simvol fərqi
#: yaradır və oxşarlıq həddini keçir — yəni hər iki forma tutulur.
#:
#: KİRİL QƏSDƏN YOXDUR: yarımçıq kiril xəritəsi (yalnız bir neçə hərf)
#: adların bir qismini çevirib bir qismini çevirməzdi və nəticə
#: proqnozlaşdırılmaz olardı. Tam kiril mətn uyğunlaşmır → sətir "Şübhəli
#: Uyğunlaşma" növbəsinə düşür, yəni səhv təyinat yox, insan yoxlaması olur.
_TRANSLITERATION: Final[dict[str, str]] = {
    "ə": "a",
    "ı": "i",
    "ş": "s",
    "ç": "c",
    "ğ": "g",
    "ö": "o",
    "ü": "u",
}

#: Ən yaxşı iki namizədin fərqi bundan azdırsa nəticə QƏBUL EDİLMİR.
#: "Əliyev Elvin" ↔ {"Əliyev Elnur", "Əliyev Elvin"} kimi hallarda təsadüfi
#: qalibi seçmək əvəzinə sətir insana göndərilir.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits` (`ERP_MATCH_AMBIGUITY_MARGIN`,
#: seed: migrations/032). Marja müəssisənin ad bazasının "sıxlığından" asılıdır:
#: eyni soyadlı çoxlu işçisi olan şəbəkədə daha geniş marja lazımdır, əks halda
#: "Şübhəli Uyğunlaşma" növbəsi boş qalar və səhv təyinat sükutla keçər.
FALLBACK_AMBIGUITY_MARGIN: Final[float] = fallback_float(SystemLimitKey.ERP_MATCH_AMBIGUITY_MARGIN)


@runtime_checkable
class MatchDirectory(Protocol):
    """Uyğunlaşma üçün lazım olan axtarışlar.

    Protocol olaraq təyin olunub ki, uyğunlaşma məntiqi DB-siz test edilə
    bilsin — qayda dəyişikliyi (bölmə 6) sorğu qatına toxunmadan yoxlanılır.
    """

    def store_for(self, server_id: ErpServerId, store_code: str) -> StoreId | None:
        """`store_server_mapping` üzrə mağaza kodunu həll edir."""
        ...

    def employee_by_seller_id(self, store_id: StoreId, seller_id: str) -> EmployeeId | None:
        """`employees.one_c_seller_id` üzrə dəqiq uyğunluq."""
        ...

    def employees_in_store(self, store_id: StoreId) -> Sequence[tuple[EmployeeId, str]]:
        """Mağazanın AKTİV işçiləri: `(id, "Ad Soyad")`."""
        ...


@dataclass(frozen=True)
class _Candidate:
    employee_id: EmployeeId
    name: str
    score: float


class SalesMatcher:
    """Bir serverin sənədlərini işçi/mağazaya bağlayır."""

    def __init__(
        self,
        directory: MatchDirectory,
        *,
        threshold: float = NAME_MATCH_THRESHOLD,
        ambiguity_margin: float | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        """
        Args:
            ambiguity_margin: AÇIQ üstünlük — verilərsə ROOT dəyəri OXUNMUR.
            limits: `system_limits`-ə açılan pəncərə; verilməzsə fallback.
        """
        self._directory = directory
        self._threshold = threshold
        self._explicit_margin = ambiguity_margin
        self._limits = limits or InfrastructureLimits()

    def _ambiguity_margin(self) -> float:
        """Qərarsızlıq marjası — HƏR SƏTİRDƏ yenidən oxunur.

        Sinxronizasiya dövrü uzun sürür və Root marjanı onun ortasında dəyişə
        bilər; oxu ucuzdur (bir sətirlik sorğu), səhv təyinat isə bahalıdır
        (işçiyə yanlış satış xalı).
        """
        if self._explicit_margin is not None:
            return self._explicit_margin
        return self._limits.float_of(SystemLimitKey.ERP_MATCH_AMBIGUITY_MARGIN)

    def match(self, record: OneCSaleRecord, server_id: ErpServerId) -> MatchResult:
        store_id = self._directory.store_for(server_id, record.store_code)
        if store_id is None:
            # Mağaza xəritələnməyibsə bu, konfiqurasiya boşluğudur — admin
            # `store_server_mapping`-ə sətir əlavə etməlidir. Sənəd İTMİR:
            # növbədə qalır və xəritələmə düzəldiləndə əl ilə təyin olunur.
            return MatchResult(
                record=record,
                confidence=MatchConfidence.UNASSIGNED,
                reason=(
                    f"«{record.store_code}» mağaza kodu bu serverə bağlı heç bir "
                    "mağazaya uyğun gəlmir — Server↔Mağaza xəritələməsini yoxlayın."
                ),
            )

        if record.seller_id:
            employee_id = self._directory.employee_by_seller_id(store_id, record.seller_id)
            if employee_id is not None:
                return MatchResult(
                    record=record,
                    confidence=MatchConfidence.EXACT_MATCH,
                    employee_id=employee_id,
                    store_id=store_id,
                    reason="1C satıcı ID-si üzrə dəqiq uyğunluq.",
                )

        return self._match_by_name(record, store_id)

    # ---------------------------- ad fallback -------------------------------- #

    def _match_by_name(self, record: OneCSaleRecord, store_id: StoreId) -> MatchResult:
        if not record.seller_name:
            return MatchResult(
                record=record,
                confidence=MatchConfidence.UNASSIGNED,
                store_id=store_id,
                reason=(
                    f"1C satıcı ID-si («{record.seller_id or '—'}») heç bir işçiyə "
                    "bağlanmayıb və sənəddə satıcı adı yoxdur."
                ),
            )

        candidates = self._score_candidates(record.seller_name, store_id)
        if not candidates:
            return MatchResult(
                record=record,
                confidence=MatchConfidence.UNASSIGNED,
                store_id=store_id,
                reason=f"«{record.seller_name}» adına uyğun aktiv işçi tapılmadı.",
            )

        best = candidates[0]
        if best.score < self._threshold:
            return MatchResult(
                record=record,
                confidence=MatchConfidence.UNASSIGNED,
                store_id=store_id,
                reason=(
                    f"«{record.seller_name}» adı heç bir işçiyə kifayət qədər "
                    f"yaxın deyil (ən yaxını «{best.name}», {best.score:.0%})."
                ),
            )

        runner_up = candidates[1] if len(candidates) > 1 else None
        if runner_up is not None and (best.score - runner_up.score) < self._ambiguity_margin():
            # Bax modul başlığı: təxmin etmək boş buraxmaqdan bahadır.
            _log.warning(
                "ERP_MATCH_AMBIGUOUS",
                extra={
                    "document_id": record.document_id,
                    "best": best.score,
                    "runner_up": runner_up.score,
                },
            )
            return MatchResult(
                record=record,
                confidence=MatchConfidence.UNASSIGNED,
                store_id=store_id,
                reason=(
                    f"«{record.seller_name}» adı iki işçiyə eyni dərəcədə uyğundur "
                    f"(«{best.name}» və «{runner_up.name}») — seçim əl ilə edilməlidir."
                ),
            )

        return MatchResult(
            record=record,
            confidence=MatchConfidence.LOW_CONFIDENCE_MATCH,
            employee_id=best.employee_id,
            store_id=store_id,
            reason=(
                f"1C satıcı ID-si bağlanmayıb; ad oxşarlığı ilə «{best.name}» "
                f"seçildi ({best.score:.0%}) — təsdiq tələb olunur."
            ),
        )

    def _score_candidates(self, seller_name: str, store_id: StoreId) -> list[_Candidate]:
        target = normalize_name(seller_name)
        if not target:
            return []
        scored = [
            _Candidate(
                employee_id=employee_id,
                name=full_name,
                score=name_similarity(seller_name, full_name),
            )
            for employee_id, full_name in self._directory.employees_in_store(store_id)
        ]
        scored.sort(key=lambda candidate: candidate.score, reverse=True)
        return scored


# --------------------------------------------------------------------------- #
# Ad normalizasiyası
# --------------------------------------------------------------------------- #


def normalize_name(name: str) -> str:
    """Adı müqayisəyə hazır formaya salır.

    Kiçik hərf → transliterasiya → yalnız hərf/rəqəm → sözlər əlifba sırası
    ilə. Söz sırasının sıralanması "Ad Soyad" ↔ "Soyad Ad" fərqini aradan
    qaldırır: 1C-də hansı sıranın istifadə olunduğu konfiqurasiyadan asılıdır.
    """
    lowered = name.strip().lower()
    translated = "".join(_TRANSLITERATION.get(char, char) for char in lowered)
    words = ["".join(ch for ch in word if ch.isalnum()) for word in translated.split()]
    return " ".join(sorted(word for word in words if word))


def name_similarity(left: str, right: str) -> float:
    """0.0–1.0 arası oxşarlıq (normalizasiyadan sonra)."""
    normalized_left = normalize_name(left)
    normalized_right = normalize_name(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


__all__ = [
    "FALLBACK_AMBIGUITY_MARGIN",
    "MatchDirectory",
    "SalesMatcher",
    "name_similarity",
    "normalize_name",
]
