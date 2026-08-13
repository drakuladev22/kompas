"""Sübut şəkilləri üçün lokal fayl-keşi — Faza 3.9.

──────────────────────────────────────────────────────────────────────────────
NİYƏ LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
"Cərimələrim" ekranı 30 sətir göstərirsə və keş olmasaydı, ekran hər
açılışda 30 Drive sorğusu edərdi. Drive API istifadəçi başına ~100
sorğu/100 saniyə verir — ekranı üç dəfə açmaq kvotanı tükədərdi, üstəlik
hər açılış saniyələrlə çəkərdi.

──────────────────────────────────────────────────────────────────────────────
İKİ HƏDD: YAŞ VƏ ÖLÇÜ
──────────────────────────────────────────────────────────────────────────────
Sübut şəkli DƏYİŞMƏZ-dir (yükləndikdən sonra redaktə olunmur), ona görə
TTL uzun ola bilər. Lakin keş sonsuz böyüməməlidir: mağaza PC-sinin diski
məhduddur. Ona görə ikinci hədd — ümumi ölçü — var və aşıldıqda ƏN KÖHNƏ
ISTIFADƏ OLUNMUŞ fayllar silinir (LRU).

Keş yalnız PERFORMANS üçündür: fayl silinsə sistem sadəcə yenidən çəkir.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.domain.policies import SystemLimitKey
from src.domain.value_objects.storage import ImageSize, StorageReference
from src.infrastructure.config.limits import InfrastructureLimits, fallback_int
from src.shared.logger import get_logger

_log = get_logger(__name__)

#: HƏR İKİSİ FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`IMAGE_CACHE_TTL_SECONDS`, `IMAGE_CACHE_MAX_BYTES`; seed: migrations/032).
#: Kiosk PC-sinin diski 128 GB da ola bilər, 2 TB da — 256 MB birinci halda
#: nəzərəçarpan pay, ikincisində isə lazımsız dar tavandır.
FALLBACK_TTL_SECONDS: Final[int] = fallback_int(SystemLimitKey.IMAGE_CACHE_TTL_SECONDS)
FALLBACK_MAX_BYTES: Final[int] = fallback_int(SystemLimitKey.IMAGE_CACHE_MAX_BYTES)


def default_cache_dir() -> Path:
    """`%APPDATA%/KompasOS/image_cache/` (Windows) və ya XDG ekvivalenti."""
    override = os.environ.get("KOMPASOS_IMAGE_CACHE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "KompasOS" / "image_cache"


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    files: int
    total_bytes: int


class ImageCache:
    """Sadə, thread-safe LRU fayl-keşi."""

    def __init__(
        self,
        directory: Path | str | None = None,
        *,
        ttl_seconds: int | None = None,
        max_bytes: int | None = None,
        limits: InfrastructureLimits | None = None,
    ) -> None:
        self._dir = Path(directory) if directory is not None else default_cache_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._explicit_ttl = ttl_seconds
        self._explicit_max_bytes = max_bytes
        self._limits = limits or InfrastructureLimits()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _ttl(self) -> int:
        """Keş faylının ömrü — HƏR OXUDA/TƏMİZLƏMƏDƏ həll olunur.

        Keş tətbiqin bütün sessiyası boyu yaşayır; dəyəri konstruktorda
        dondursaydıq, Root-un yeni tavanı yalnız yenidən başlatmadan sonra
        qüvvəyə minərdi — halbuki dəyişiklik məhz disk dolduqda edilir.
        """
        if self._explicit_ttl is not None:
            return self._explicit_ttl
        return self._limits.int_of(SystemLimitKey.IMAGE_CACHE_TTL_SECONDS)

    def _max_bytes(self) -> int:
        """Keşin disk tavanı — hər `store()`-dan sonrakı budamada oxunur."""
        if self._explicit_max_bytes is not None:
            return self._explicit_max_bytes
        return self._limits.int_of(SystemLimitKey.IMAGE_CACHE_MAX_BYTES)

    # ------------------------------- açar ------------------------------------ #

    def _path_for(self, reference: StorageReference, size: ImageSize) -> Path:
        # Fayl adı kimi xam `file_id` istifadə etmək olmaz: Drive ID-si
        # `/` və `-` saxlaya bilər və fayl sistemində qovluq keçidinə
        # çevrilə bilər. Hash həm təhlükəsiz, həm sabit uzunluqdadır.
        digest = hashlib.sha256(f"{reference.cache_key}|{size.value}".encode()).hexdigest()
        return self._dir / f"{digest}.bin"

    # ------------------------------ əməliyyat -------------------------------- #

    def get(self, reference: StorageReference, size: ImageSize) -> bytes | None:
        path = self._path_for(reference, size)
        with self._lock:
            if not path.exists():
                self._misses += 1
                return None
            age = time.time() - path.stat().st_mtime
            if age > self._ttl():
                path.unlink(missing_ok=True)
                self._misses += 1
                return None
            data = path.read_bytes()
            # LRU üçün "son istifadə" anını yenilə.
            os.utime(path, None)
            self._hits += 1
            return data

    def put(self, reference: StorageReference, size: ImageSize, data: bytes) -> None:
        path = self._path_for(reference, size)
        with self._lock:
            # Atomik yazı: yarımçıq fayl heç vaxt keşdə "hazır" görünməsin.
            temporary = path.with_suffix(".part")
            temporary.write_bytes(data)
            temporary.replace(path)
            self._evict_if_needed_locked()

    def invalidate(self, reference: StorageReference) -> None:
        with self._lock:
            for size in ImageSize:
                self._path_for(reference, size).unlink(missing_ok=True)

    def clear(self) -> None:
        with self._lock:
            for path in self._dir.glob("*.bin"):
                path.unlink(missing_ok=True)

    @property
    def stats(self) -> CacheStats:
        with self._lock:
            files = list(self._dir.glob("*.bin"))
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                files=len(files),
                total_bytes=sum(f.stat().st_size for f in files),
            )

    # ------------------------------- LRU ------------------------------------- #

    def _evict_if_needed_locked(self) -> None:
        files = [(f, f.stat()) for f in self._dir.glob("*.bin")]
        total = sum(stat.st_size for _, stat in files)
        # Tavan BİR DƏFƏ oxunur: budama dövrünün ortasında dəyişən hədd
        # "nə qədər sildik?" sualını cavabsız qoyardı.
        max_bytes = self._max_bytes()
        if total <= max_bytes:
            return
        # Ən köhnə istifadə olunan əvvəl silinir.
        files.sort(key=lambda item: item[1].st_atime)
        removed = 0
        for path, stat in files:
            if total <= max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= stat.st_size
            removed += 1
        _log.info(
            "IMAGE_CACHE_EVICTED",
            extra={"removed_files": removed, "remaining_bytes": total},
        )


__all__ = [
    "FALLBACK_MAX_BYTES",
    "FALLBACK_TTL_SECONDS",
    "CacheStats",
    "ImageCache",
    "default_cache_dir",
]
