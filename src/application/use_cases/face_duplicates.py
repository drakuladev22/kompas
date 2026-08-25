"""Dublikat-işçi aşkarlaması — `v2backlog.md` Faza 6.2.

    "Duplicate-Employee Aşkarlanması: üz-embedding-oxşarlığına əsaslanan,
     EYNİ tenant daxilində 2-ci qeydiyyat şübhəsi (Exception Engine-ə bağlı)."

──────────────────────────────────────────────────────────────────────────────
NAXIŞ — HR-1/HR-2/HR-3/UX-7 İLƏ EYNİ QAYDA MÜHƏRRİKİ
──────────────────────────────────────────────────────────────────────────────
Bu, `ExceptionRule`-un adi bir implementasiyasıdır: motor DƏYİŞMİR, yalnız
`register_rule(...)` ilə qoşulur (bax `composition.py`). Qayda YAZMIR —
yalnız tapıntı qaytarır; təkrar-qapaq, ciddiyyət defoltu, audit və bildiriş
motorundadır (bax `exception_engine.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
HƏDD NİYƏ YENİ ROOT AÇARI DEYİL
──────────────────────────────────────────────────────────────────────────────
«Bu iki vektor eyni adamdırmı?» sualının həddi sistemdə ARTIQ VAR:
`FACE_MATCH_TOLERANCE`. Doğrulama axını məhz bu həddin İÇİNDƏ olan məsafəni
«eyni adam» kimi qəbul edir — dublikat aşkarlaması EYNİ standartdan istifadə
etməsəydi, iki fərqli «eynilik» tərfi yaranardı: doğrulama «eynidir» deyən
cütlük dublikat siyahısına düşməzdi (və ya əksinə). Root toleransı dəyişəndə
hər iki sualın cavabı BİRLİKDƏ dəyişir — bu, xüsusiyyət deyil, tələbdir.

──────────────────────────────────────────────────────────────────────────────
MƏSAFƏ NİYƏ SAF PYTHONDA (`math.dist`) HESABLANIR
──────────────────────────────────────────────────────────────────────────────
`FaceMatcher.distance` `face_recognition.face_distance` çağırır — o, NUMPY
və Dlib kitabxanasını yükləyir. Gecəlik qayda bunu AÇA BİLMƏZ (server başlığı
olmayan iş prosesində də işləməlidir) və N² müqayisə üçün lazım olan yeganə
şey EVKLİD məsafəsinin ÖZÜDÜR. `face_distance`-ın hesablamaq olduğu formula
məhz Evkliddir (`face_matcher.py::distance` başlığı) — `math.dist` EYNİ
nəticəni verir, kitabxana asılılığı olmadan. Metrikanı dəyişmək riski isə
həmin faylın öz şərhində bağlanıb: metrikanın TƏK mənbəyi oradadır və o,
dəyişsə buradakı iddia testlə tutulur.
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING, Final, Protocol

from src.domain.value_objects.exception_signals import (
    DUPLICATE_FACE_SOURCE,
    ExceptionFinding,
    RuleEvaluationContext,
)

if TYPE_CHECKING:
    from src.domain.value_objects.face_recognition import FaceProfile
    from src.domain.value_objects.identifiers import TenantId

#: Bir cütlüyün tapıntı kontekstindəki yuvarlaqlaşdırma dəqiqliyi — ekran
#: oxuna bilən «0.31» forması üçündür, hesablama tam dəqiqliklə gedir.
_DISPLAY_PRECISION: Final = 4


class DuplicateFaceExceptionRule:
    """6.2 — eyni üzlü ikinci qeydiyyat şübhəsi (gecəlik, tenant-miqyaslı).

    ──────────────────────────────────────────────────────────────────────────
    PORT NAXIŞI — OverdueFaceEnrollmentRule İLƏ EYNİ
    ──────────────────────────────────────────────────────────────────────────
    Repo LAQEYD çağırılır: yalnız motor `evaluate()` dedikdə sorğu gedir.
    Kompozisiya anında profil siyahısını çıxarsaydıq, HƏR sessiya qurulanda
    bütün heyətin vektorları deşifrə olunardı — həm PERF-1 büdcəsi, həm də
    biometrik datanın gündəlik axına düşməsi baxımından yanlış olardı.
    """

    def __init__(self, *, profiles: AllProfilesReader) -> None:
        self._profiles = profiles

    @property
    def source_code(self) -> str:
        return DUPLICATE_FACE_SOURCE

    @property
    def name_az(self) -> str:
        return "Eyni üzlü iki qeydiyyat"

    def evaluate(self, context: RuleEvaluationContext) -> list[ExceptionFinding]:
        """Cütləri tapır — HƏR CÜTLÜYÜ BİR DƏFƏ, kiçik-ID əvvəl.

        `dedupe_key` = cüt + gün. Yalnız gün seçilsəydi, həll olunmamış cüt
        hər gecə YENİ sətir açardı; yalnız cüt seçilsəydi, HR bir dəfə baxıb
        bağlasaydı və ŞÜBHƏ qalırdı (məs. üçüncü oxşar qeydiyyat), problem
        susardı — UX-7 ilə eyni gündəlik ritm.
        """
        tolerance = context.limit_float(
            "FACE_MATCH_TOLERANCE",
            _default_tolerance(),
        )
        profiles = sorted(
            (
                profile
                for profile in self._profiles.list_all_profiles(context.tenant_id)
                if profile.embedding is not None
            ),
            key=lambda profile: profile.employee_id,
        )
        findings: list[ExceptionFinding] = []
        today = context.as_of.date().isoformat()

        for left, right in itertools.combinations(profiles, 2):
            assert left.embedding is not None and right.embedding is not None
            if left.embedding.dimension != right.embedding.dimension:
                # Fərqli ölçü = kitabxana versiyası dəyişib — bu cüt MÜQAYISƏSİZ-
                # dir; «uyğunsuz» kimi siqnal etmək yalan pozitiv yaradardı.
                continue
            distance = math.dist(left.embedding.values, right.embedding.values)
            if distance >= tolerance:
                continue

            pair_key = f"{left.employee_id}:{right.employee_id}"
            store = left.store_id or right.store_id
            assert store is not None  # qeydiyyatlı profil mağazasız ola bilməz
            findings.append(
                ExceptionFinding(
                    employee_id=left.employee_id,
                    store_id=store,
                    detail=(
                        "İki fərqli qeydiyyatın üz vektorları sistemin «eyni adam» "
                        f"toleransından yaxındır (məsafə {round(distance, _DISPLAY_PRECISION)} "
                        f"< hədd {round(tolerance, _DISPLAY_PRECISION)}). Araşdırma "
                        "qərarı HR-dadır — qeydiyyatlar avtomatik silinmir."
                    ),
                    context={
                        "pair_employee_id": str(right.employee_id),
                        "distance": round(distance, _DISPLAY_PRECISION),
                        "tolerance": round(tolerance, _DISPLAY_PRECISION),
                        "left_store_id": (
                            str(left.store_id) if left.store_id is not None else None
                        ),
                        "right_store_id": (
                            str(right.store_id) if right.store_id is not None else None
                        ),
                    },
                    dedupe_key=f"{pair_key}:{today}",
                )
            )
        return findings


class AllProfilesReader(Protocol):
    """`FaceEmbeddingRepository.list_all_profiles`-un QAYDANIN GÖRDÜYÜ üzü.

    Struktural protokoldur (`PostgresFaceEmbeddingRepository` onsuz da bu
    metodu daşıyır) — qayda geniş repo portunu TANIMIR demək olur, testlərdə
    isə tək metodlu sahtə kifayət edir.
    """

    def list_all_profiles(self, tenant_id: TenantId) -> list[FaceProfile]: ...


def _default_tolerance() -> float:
    """`FACE_MATCH_TOLERANCE` seed-inin güzgüsü — snapshot-da açar yoxdursa.

    `DEFAULT_LIMITS`-dən oxunur (kodda ikinci ədəd YAZILMIR); snapshot onsuz da
    motor tərəfindən `SystemLimits.all_for()` ilə doldurulur, bu yol yalnız
    test sahtələrinin natamam lüğətinə qarşı fail-softdur.
    """
    from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey  # noqa: PLC0415

    try:
        return float(DEFAULT_LIMITS[SystemLimitKey.FACE_MATCH_TOLERANCE])
    except (KeyError, TypeError, ValueError):  # pragma: no cover — seed bozuksa
        return 0.6


__all__ = [
    "DUPLICATE_FACE_SOURCE",
    "AllProfilesReader",
    "DuplicateFaceExceptionRule",
]
