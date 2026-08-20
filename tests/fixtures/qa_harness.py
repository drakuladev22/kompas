"""QA-FULL ölçmə dəsti — «yavaşdır» hissini rəqəmə çevirən alətlər.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL, HƏR TESTDƏ YENİDƏN YAZILMASIN
──────────────────────────────────────────────────────────────────────────────
Layihədə ölçmə kodu ARTIQ var idi, lakin hər dəfə YERLİ olaraq yenidən
yazılırdı: `test_session_roundtrips.py` öz `_FakeConnection`-unu qurur,
`test_read_batch_scope.py` başqasını. Nəticədə hər nüsxə bir az fərqlidir və
biri düzəliləndə digəri köhnə qalır — «hər qayda İKİ yerdə» probleminin
ölçmə tərəfdəki eynisi.

Bu modul həmin alətləri BİR yerə yığır. Məqsəd yeni test yazmaq deyil,
QA-FULL fazalarının (performans, N+1, yaddaş sızması, donma) eyni ölçü
vahidindən istifadə etməsidir — «əvvəl X, sonra Y» müqayisəsi yalnız ölçü
eyni olduqda mənalıdır.

──────────────────────────────────────────────────────────────────────────────
NƏ ÖLÇÜLÜR VƏ NİYƏ MƏHZ BU
──────────────────────────────────────────────────────────────────────────────
* **Vaxt** (`Timings`) — istifadəçinin gözlədiyi müddət.
* **Gediş-gəliş sayı** (`StatementRecorder`) — səbəbin ÖZÜ. Supabase
  pooler-inə bir gediş-gəliş ~206 ms çəkir (PERF-1-də ölçülüb), yəni ekranı
  yavaşladan şey alqoritm deyil, sorğu SAYIdır. Vaxt ölçən test şəbəkədən
  asılı olar və CI-da səbəbsiz sınardı; sorğu sayı isə determinstikdir.
* **Yaddaş** (`memory_growth`) — 27 ekranı dəfələrlə aç-bağla edəndə artım
  dayanırmı. Tək ölçü aldadıcıdır (Python allocator dərhal qaytarmır), ona
  görə funksiya BİR rəqəm yox, dövr-be-dövr SIRA qaytarır.
"""

from __future__ import annotations

import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import pairwise
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


# --------------------------------------------------------------------------- #
# 1 — Vaxt
# --------------------------------------------------------------------------- #


@dataclass
class Timings:
    """Adlandırılmış ölçülərin toplusu — millisaniyə ilə.

    Sözlük əvəzinə sinif seçilib ki, `slowest()` sıralaması ölçünün YANINDA
    dursun: hesabatı çıxaran kod hər dəfə eyni sıralamanı yenidən yazsaydı,
    iki fazada iki fərqli «ən yavaş 10» tərifi yaranardı.
    """

    samples: dict[str, list[float]] = field(default_factory=dict)

    @contextmanager
    def measure(self, label: str) -> Iterator[None]:
        """Blokun müddətini `label` altında yazır."""
        start = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter() - start) * 1000
            self.samples.setdefault(label, []).append(elapsed_ms)

    def call(self, label: str, action: Callable[[], Any]) -> Any:
        """`measure()`-in çağırış forması — nəticəni QAYTARIR."""
        with self.measure(label):
            return action()

    def best(self, label: str) -> float:
        """ƏN SÜRƏTLİ nümunə.

        Orta dəyər DEYİL: ölçmə maşınında paralel iş (antivirus, başqa test
        prosesi) təsadüfi ZİRVƏLƏR yaradır və orta onları içinə çəkir. Ən
        sürətli nümunə «bu əməliyyat ən yaxşı halda nə qədərdir» sualına
        cavab verir — reqressiya axtarışında lazım olan da budur.
        """
        return min(self.samples[label])

    def slowest(self, limit: int = 10) -> list[tuple[str, float]]:
        """Ən yavaş `limit` ölçü — (ad, ms), azalan sıra ilə."""
        ranked = sorted(
            ((label, min(values)) for label, values in self.samples.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        return ranked[:limit]

    def table(self, limit: int = 10) -> str:
        """Hesabat üçün hazır mətn cədvəli."""
        rows = [f"{label:<52} {ms:>9.1f} ms" for label, ms in self.slowest(limit)]
        return "\n".join(rows)


# --------------------------------------------------------------------------- #
# 2 — Gediş-gəliş sayı (N+1 aşkarlanması)
# --------------------------------------------------------------------------- #


class _RecordingCursor:
    """`execute()`-u qeyd edən, boş nəticə qaytaran kursor."""

    def __init__(self, recorder: StatementRecorder) -> None:
        self._recorder = recorder

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> _RecordingCursor:
        self._recorder.record(sql, params)
        return self

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []

    def __iter__(self) -> Iterator[Any]:
        return iter(())


class StatementRecorder:
    """Göndərilən HƏR SQL sorğusunu yazır — N+1-in yeganə etibarlı ölçüsü.

    Bazaya bağlanmır: qayıdan nəticə həmişə boşdur. Bu, QƏSDƏNDİR — ölçülən
    şey nəticə deyil, SORĞU AXINIDIR. Real baza tələb etsəydik ölçü şəbəkədən
    asılı olar və CI-da işləməzdi.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[Any] = []

    # -- yazma ------------------------------------------------------------- #

    def record(self, sql: str, params: object = None) -> None:
        self.statements.append(" ".join(sql.split()))
        self.params.append(params)

    def reset(self) -> None:
        self.statements.clear()
        self.params.clear()

    # -- bağlantı protokolu ------------------------------------------------ #

    def execute(self, sql: str, params: Any = None) -> _RecordingCursor:
        self.record(sql, params)
        return _RecordingCursor(self)

    def cursor(self, *_args: object, **_kwargs: object) -> _RecordingCursor:
        return _RecordingCursor(self)

    def commit(self) -> None:
        self.record("COMMIT")

    def rollback(self) -> None:
        self.record("ROLLBACK")

    def close(self) -> None:
        return None

    # -- ölçü -------------------------------------------------------------- #

    @property
    def count(self) -> int:
        return len(self.statements)

    def matching(self, fragment: str) -> list[str]:
        """Verilmiş parçanı ehtiva edən sorğular — kiçik/böyük hərfsiz."""
        needle = fragment.lower()
        return [sql for sql in self.statements if needle in sql.lower()]

    def repeated(self, *, minimum: int = 3) -> dict[str, int]:
        """EYNİ sorğunun `minimum` və daha çox dəfə təkrarı — N+1 imzası.

        Parametrlər NƏZƏRƏ ALINMIR: N+1-in imzası məhz eyni SQL mətninin
        müxtəlif parametrlərlə dövrədə göndərilməsidir. Parametrləri də
        müqayisə etsəydik naxış görünməz qalardı.
        """
        counts: dict[str, int] = {}
        for sql in self.statements:
            counts[sql] = counts.get(sql, 0) + 1
        return {sql: n for sql, n in counts.items() if n >= minimum}

    @contextmanager
    def budget(self, limit: int, *, label: str = "əməliyyat") -> Iterator[None]:
        """Blok `limit` sorğudan çox göndərməməlidir.

        Büdcə naxışı PERF-1-dən gəlir: hədd rəqəmi testdə AÇIQ yazılır ki,
        artım təsadüfən deyil, qərarla baş versin.
        """
        before = self.count
        yield
        spent = self.count - before
        if spent > limit:
            sent = "\n  ".join(self.statements[before:])
            msg = f"{label}: {spent} sorğu göndərildi, büdcə {limit}\n  {sent}"
            raise AssertionError(msg)


# --------------------------------------------------------------------------- #
# 3 — Yaddaş
# --------------------------------------------------------------------------- #


def memory_growth(action: Callable[[], Any], *, cycles: int = 10) -> list[int]:
    """`action`-u `cycles` dəfə icra edir, hər dövrdən sonrakı yaddaşı qaytarır.

    Qaytarılan SIRA-dır, tək rəqəm yox: Python allocator azad edilmiş bloku
    dərhal əməliyyat sisteminə qaytarmır, ona görə «əvvəl/sonra» müqayisəsi
    həmişə artım göstərir və heç nə sübut etmir. Sızmanın imzası FASİLƏSİZ
    ARTIMDIR — sıra bunu görünən edir.

    Ölçü `tracemalloc`-dandır (prosesin RSS-i yox): o, YALNIZ Python
    obyektlərini sayır, yəni Qt-nin C++ tərəfindəki müvəqqəti buferləri
    nəticəni bulandırmır.
    """
    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    try:
        # BİR İSTİLİK DÖVRƏSİ: ilk çağırış modul idxalı, QSS kompilyasiyası və
        # keşlərin qurulması ilə birlikdə gəlir — o, sızma deyil, birdəfəlik
        # qiymətdir və sıraya qatılsaydı hər ölçmə «artım var» deyərdi.
        action()
        readings: list[int] = []
        for _ in range(cycles):
            action()
            current, _peak = tracemalloc.get_traced_memory()
            readings.append(current)
        return readings
    finally:
        if started_here:
            tracemalloc.stop()


def grows_monotonically(readings: list[int], *, tolerance: float = 0.02) -> bool:
    """Sıra FASİLƏSİZ artırmı — sızma əlaməti.

    `tolerance` KİÇİK dalğalanmanı udur: keş genişlənməsi və ya sətir
    internləşdirilməsi bir neçə kilobayt oynadır və hər ölçmə «sızma var»
    deyərdi. Yalnız SON dəyər BİRİNCİdən nəzərəçarpacaq dərəcədə böyükdürsə
    və aralıq dəyərlər də artırsa, nəticə `True`-dur.
    """
    if len(readings) < 3:
        return False
    first, last = readings[0], readings[-1]
    if last <= first * (1 + tolerance):
        return False
    rising = sum(1 for a, b in pairwise(readings) if b > a)
    return rising >= len(readings) - 2


__all__ = [
    "StatementRecorder",
    "Timings",
    "grows_monotonically",
    "memory_growth",
]
