#!/usr/bin/env python3
"""Argon2id parametrlərinin ölçülməsi (risk R5, spesifikasiya bölmə 2).

NİYƏ LAZIMDIR: OWASP tövsiyəsi (m=64 MiB, t=3, p=4) müasir CPU-da ~100 ms
verir, lakin köhnə mağaza kiosk PC-lərində 300–500 ms ola bilər. PIN yoxlaması
istifadəçinin gözlədiyi anda baş verdiyi üçün bu, birbaşa UX məsələsidir.

QAYDA: parametrləri AZALTMAQ təhlükəsizliyi zəiflədir — ölçmə nəticəsi
`docs/security_decisions.md`-də qeyd olunmadan dəyişiklik edilməməlidir.

İSTİFADƏ:
    python scripts/benchmark_argon2.py
    python scripts/benchmark_argon2.py --target-ms 250
"""

from __future__ import annotations

import argparse
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from typing import TypedDict

from argon2 import PasswordHasher, Type


class Argon2Params(TypedDict):
    """`**params` açılışı mypy-a `dict[str, int]`-dən dəqiq keçmir.

    Adi `dict[str, int]` ilə `PasswordHasher(**params, ...)` mypy-ı "expected
    str" xətası verirdi — mypy `**` açılışında lüğətin İSTƏNİLƏN açarı ola
    biləcəyini fərz edir və `encoding: str` parametri ilə toqquşdurur.
    `TypedDict` açarları qabaqcadan sabitləyir, ona görə açılış dəqiq
    yoxlanılır və `PasswordHasher`-in özü DƏYİŞMİR.
    """

    time_cost: int
    memory_cost: int
    parallelism: int


#: İstehsalat parametrləri (`hashing.py` ilə eyni).
PRODUCTION: Argon2Params = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 4}

#: Sınanan alternativlər — hamısı OWASP-ın qəbul etdiyi diapazondadır.
CANDIDATES: list[Argon2Params] = [
    {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 4},  # istehsalat
    {"time_cost": 2, "memory_cost": 64 * 1024, "parallelism": 4},
    {"time_cost": 3, "memory_cost": 32 * 1024, "parallelism": 4},
    {"time_cost": 2, "memory_cost": 32 * 1024, "parallelism": 2},
    {"time_cost": 4, "memory_cost": 16 * 1024, "parallelism": 2},  # OWASP minimum
]

SAMPLES = 5


@dataclass
class Measurement:
    params: Argon2Params
    hash_ms: float
    verify_ms: float

    @property
    def label(self) -> str:
        return (
            f"t={self.params['time_cost']} "
            f"m={self.params['memory_cost'] // 1024}MiB "
            f"p={self.params['parallelism']}"
        )

    @property
    def is_production(self) -> bool:
        return self.params == PRODUCTION


def measure(params: dict[str, int], *, samples: int = SAMPLES) -> Measurement:
    hasher = PasswordHasher(**params, hash_len=32, salt_len=16, type=Type.ID)
    # Yalnız ölçmə üçün sabit giriş — real sirr deyil.
    sample_input = "olcme-ucun-numune-deyer-4821"

    hash_times: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        digest = hasher.hash(sample_input)
        hash_times.append((time.perf_counter() - start) * 1000)

    verify_times: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        hasher.verify(digest, sample_input)
        verify_times.append((time.perf_counter() - start) * 1000)

    return Measurement(
        params=params,
        hash_ms=statistics.median(hash_times),
        verify_ms=statistics.median(verify_times),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Argon2id parametr ölçməsi")
    parser.add_argument(
        "--target-ms",
        type=float,
        default=250.0,
        help="Qəbul edilən maksimum yoxlama vaxtı (defolt 250 ms)",
    )
    parser.add_argument("--samples", type=int, default=SAMPLES)
    args = parser.parse_args(argv)

    sys.stdout.write(f"Maşın: {platform.processor() or platform.machine()}\n")
    sys.stdout.write(f"Python: {platform.python_version()}\n")
    sys.stdout.write(f"Hədəf: yoxlama <= {args.target_ms:.0f} ms\n\n")
    sys.stdout.write(f"{'Parametrlər':<28}{'hash':>10}{'verify':>10}  vəziyyət\n")
    sys.stdout.write("-" * 62 + "\n")

    results: list[Measurement] = []
    for params in CANDIDATES:
        result = measure(params, samples=args.samples)
        results.append(result)
        marker = " (İSTEHSALAT)" if result.is_production else ""
        verdict = "OK" if result.verify_ms <= args.target_ms else "YAVAŞ"
        sys.stdout.write(
            f"{result.label + marker:<28}"
            f"{result.hash_ms:>8.0f}ms{result.verify_ms:>8.0f}ms  {verdict}\n"
        )

    production = next(r for r in results if r.is_production)
    sys.stdout.write("\n")

    if production.verify_ms <= args.target_ms:
        sys.stdout.write(
            f"NƏTİCƏ: istehsalat parametrləri bu maşında {production.verify_ms:.0f} ms "
            f"verir — hədd daxilindədir. DƏYİŞİKLİK LAZIM DEYİL.\n"
        )
        return 0

    acceptable = [r for r in results if r.verify_ms <= args.target_ms and not r.is_production]
    sys.stdout.write(
        f"NƏTİCƏ: istehsalat parametrləri {production.verify_ms:.0f} ms verir — "
        f"{args.target_ms:.0f} ms həddini aşır.\n"
    )
    if acceptable:
        best = max(acceptable, key=lambda r: r.params["memory_cost"])
        sys.stdout.write(
            f"Ən güclü qəbul edilən alternativ: {best.label} ({best.verify_ms:.0f} ms).\n"
        )
    sys.stdout.write(
        "XƏBƏRDARLIQ: parametrləri azaltmaq təhlükəsizliyi zəiflədir. "
        "Dəyişiklik `docs/security_decisions.md`-də qeyd olunmalıdır.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
