"""Lisenziya vəziyyətinin yerli, şifrələnmiş keşi — Faza 3.11.

──────────────────────────────────────────────────────────────────────────────
NİYƏ FAYL, DB DEYİL
──────────────────────────────────────────────────────────────────────────────
Keş məhz DB ƏLÇATMAZ olduqda da lazımdır: `LICENSE_INACTIVE` ekranı proqram
Supabase-ə qoşula bilmədikdə də düzgün mətni (səbəb, tarix, əlaqə) göstərməli
və offline qrace sayğacı Supabase olmadan da işləməlidir. Vəziyyəti DB-də
saxlamaq bu iki tələbi də pozardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ŞİFRƏLƏNİR
──────────────────────────────────────────────────────────────────────────────
Fayl açıq JSON olsaydı `"status": "DEAKTIV"` → `"AKTIV"` düzəlişi bloklamanı
söndürərdi — Notepad ilə. AES-256-GCM həm məzmunu gizlədir, həm də (əsas
səbəb) BÜTÖVLÜYÜ təsdiqləyir: dəyişdirilmiş fayl açılmır. AAD konteksti
`license_state:<tenant_id>`-dir, yəni başqa quraşdırmanın faylını buraya
köçürmək də işləmir.

──────────────────────────────────────────────────────────────────────────────
SAATIN GERİ ÇƏKİLMƏSİNİN AŞKARLANMASI (`clock_high_water`)
──────────────────────────────────────────────────────────────────────────────
Offline qrace divar saatı ilə ölçülür — başqa yolu yoxdur, çünki müddət
günlərlə ölçülür və proqram bu müddətdə dəfələrlə söndürülüb-açılır
(`time.monotonic()` yenidən başlayır). Divar saatını isə istifadəçi dəyişə
bilir: saatı hər dəfə bir həftə geri çəkməklə qrace sonsuz uzadılardı.

Ona görə hər yazıda İNDİYƏDƏK GÖRÜLMÜŞ ƏN BÖYÜK an saxlanılır. Cari saat
ondan (dözümlülükdən artıq) geridədirsə, saat geri çəkilib. Reaksiya
QƏSDƏN mülayimdir — bloklama yox, `LICENSE_UNVERIFIED` xəbərdarlığı: eyni
simptomu ölmüş CMOS batareyası da yaradır və mağazanı bunun üstündə
dayandırmaq həddindən artıq sərt olardı.

Bu, mütləq qoruma DEYİL (fayl silinsə vəziyyət sıfırlanır) — lakin "sadəcə
saatı dəyiş" hücumunu "faylı tap, sil, sonra yenidən aktivləşməyi gözlə"
səviyyəsinə qaldırır. Fayl silindikdə isə keşlənmiş `AKTIV` də itir, yəni
hücumçu heç nə qazanmır.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import SystemLimitKey

# `CLOCK_ROLLBACK_TOLERANCE_SECONDS` BURADAN İDXAL OLUNMUR: fallback dəyəri
# artıq `InfrastructureLimits` verir (o da `DEFAULT_LIMITS`-dən oxuyur, yəni
# ədəd EYNİDİR). İkinci idxal saxlasaydıq, "hansı fallback işlədi?" sualının
# iki cavabı olardı və biri dəyişəndə digəri arxada qalardı.
from src.domain.value_objects.licensing import LicenseSnapshot
from src.infrastructure.config.limits import InfrastructureLimits
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.value_objects.identifiers import TenantId
    from src.infrastructure.security.encryption import EncryptionService

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

STATE_FILE_NAME: Final[str] = "license_state.bin"
#: Fayl formatının versiyası — gələcək sahə əlavələri köhnə faylı sındırmasın.
STATE_VERSION: Final[int] = 1


def default_state_dir() -> Path:
    """Vəziyyət faylının qovluğu (`%APPDATA%\\KompasOS` və ya XDG qarşılığı)."""
    override = os.environ.get("KOMPASOS_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "KompasOS"


class EncryptedLicenseStateStore:
    """`LicenseStateStore` portunun tətbiqi — şifrələnmiş tək fayl.

    Thread-safe: check-in arxa fon sapından yazır, UI isə oxuyur.
    """

    def __init__(
        self,
        tenant_id: TenantId,
        encryption: EncryptionService,
        *,
        directory: Path | None = None,
        rollback_tolerance_seconds: float | None = None,
        limits: InfrastructureLimits | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._encryption = encryption
        self._directory = directory or default_state_dir()
        self._path = self._directory / STATE_FILE_NAME
        # ÜÇ PİLLƏLİ MƏNBƏ, BU SIRA İLƏ: açıq arqument → ROOT (`system_limits`)
        # → modul fallback-ı. Açıq arqument birinci gəlir, çünki onu VERƏN
        # tərəf (test, xüsusi quraşdırma) niyyətini artıq bildirib və Root
        # dəyərinin onu sükutla üstələməsi "niyə mənim dəyərim işləmir?"
        # sualını doğurardı. `limits=None` halında davranış köçürmədən
        # ƏVVƏLKİ ilə hərfən eynidir (fallback = `DEFAULT_LIMITS`).
        #
        # TOLERANTLIQ BİR DƏFƏ OXUNUR: dəyər saatın geri çəkilməsini ölçür,
        # yəni oxu anının özü nəticəyə təsir edərdi — hər müqayisədə yenidən
        # oxumaq "hansı tolerantlıqla qərar verildi?" sualını cavabsız qoyardı.
        self._tolerance = (
            rollback_tolerance_seconds
            if rollback_tolerance_seconds is not None
            else (limits or InfrastructureLimits()).float_of(
                SystemLimitKey.LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS
            )
        )
        # Vaxt mənbəyi İNJEKSİYA OLUNUR — layihənin `Clock` portu ilə eyni
        # qayda (`ports.py`: "domen kodu `datetime.now()` ÇAĞIRMIR ... əks
        # halda vaxt-həssas qaydalar determinstik test oluna bilməzdi").
        # Burada bu, sırf test rahatlığı deyil: yüksək-su nişanı real saatla
        # yazılırsa, sabit vaxtla işləyən test saat divar-vaxtını keçəndə
        # QƏFİLDƏN sınır — yəni nasazlıq günün saatından asılı olardı.
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._unreadable = False

    # ------------------------------ LicenseStateStore ------------------------ #

    def load(self) -> LicenseSnapshot | None:
        state = self._read()
        payload = state.get("snapshot")
        if not isinstance(payload, dict):
            return None
        try:
            return LicenseSnapshot.from_dict(payload, checked_at=self._clock())
        except (ValueError, TypeError) as exc:
            _log.warning("LICENSE_STATE_SNAPSHOT_INVALID", extra={"error": str(exc)})
            return None

    def save(self, snapshot: LicenseSnapshot) -> None:
        with self._lock:
            state = self._read_locked()
            state["snapshot"] = snapshot.as_dict()
            state["clock_high_water"] = self._advance_high_water(
                state.get("clock_high_water"), snapshot.checked_at
            )
            self._write_locked(state)

    def first_run_at(self) -> datetime | None:
        state = self._read()
        return _parse_moment(state.get("first_run_at"))

    def clock_high_water(self) -> datetime | None:
        """İndiyədək görülmüş ən böyük an.

        `evaluate()` müddət müqayisəsini `max(indi, bu)` ilə aparır — saatı
        geri çəkməklə bitmiş lisenziyanı yenidən açmaq mümkün olmasın.
        """
        state = self._read()
        return _parse_moment(state.get("clock_high_water"))

    def clock_rollback_detected(self, now: datetime) -> bool:
        """Saat əvvəl görülmüş ən yüksək andan geriyə çəkilibmi.

        Yan təsir olaraq yüksək-su nişanını irəliləyir — belə ki, sual
        verildiyi hər an "görülmüş" sayılır və növbəti geri çəkilmə tutulur.
        """
        with self._lock:
            state = self._read_locked()
            previous = _parse_moment(state.get("clock_high_water"))
            rolled_back = (
                previous is not None and (previous - now).total_seconds() > self._tolerance
            )
            advanced = self._advance_high_water(state.get("clock_high_water"), now)
            if advanced != state.get("clock_high_water"):
                state["clock_high_water"] = advanced
                self._write_locked(state)

        if rolled_back and previous is not None:
            _security_log.warning(
                "LICENSE_CLOCK_ROLLBACK",
                extra={
                    "previous_high_water": previous.isoformat(),
                    "current": now.isoformat(),
                    "impact": "offline qrace uzadıla bilməz — LICENSE_UNVERIFIED",
                },
            )
        return rolled_back

    # ---------------------------------- I/O ---------------------------------- #

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_locked()

    def _read_locked(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache

        if not self._path.exists():
            self._cache = self._new_state()
            self._write_locked(self._cache)
            return self._cache

        try:
            token = self._path.read_text(encoding="ascii").strip()
            decoded = self._encryption.decrypt_json(token, context=self._context)
        except (OSError, ValueError, KeyError, KompasOSError) as exc:
            # Zədələnmiş və ya DƏYİŞDİRİLMİŞ fayl: sıfırdan başlanır.
            # Bu, hücumçuya heç nə qazandırmır — keşlənmiş `AKTIV` də itir və
            # tətbiq "heç vaxt check-in olmayıb" vəziyyətinə düşür.
            if not self._unreadable:
                self._unreadable = True
                _security_log.warning(
                    "LICENSE_STATE_UNREADABLE",
                    extra={"error": str(exc), "action": "vəziyyət sıfırlanır"},
                )
            self._cache = self._new_state()
            self._write_locked(self._cache)
            return self._cache

        if not isinstance(decoded, dict) or decoded.get("version") != STATE_VERSION:
            self._cache = self._new_state()
            self._write_locked(self._cache)
            return self._cache

        self._cache = decoded
        return decoded

    def _write_locked(self, state: dict[str, Any]) -> None:
        self._cache = state
        token = self._encryption.encrypt_json(state, context=self._context)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            # Atomik əvəzləmə: yarımçıq yazılmış fayl növbəti açılışda
            # "zədələnmiş" sayılıb qrace-i sıfırlayardı.
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(token, encoding="ascii")
            temporary.replace(self._path)
        except OSError as exc:
            _log.error(
                "LICENSE_STATE_WRITE_FAILED",
                extra={"path": str(self._path), "error": str(exc)},
            )

    def _new_state(self) -> dict[str, Any]:
        now = self._clock().isoformat()
        return {
            "version": STATE_VERSION,
            "tenant_id": str(self._tenant_id),
            "first_run_at": now,
            "clock_high_water": now,
            "snapshot": None,
        }

    def _advance_high_water(self, stored: Any, candidate: datetime) -> str:
        previous = _parse_moment(stored)
        if previous is None or candidate > previous:
            return candidate.isoformat()
        return previous.isoformat()

    @property
    def _context(self) -> str:
        return f"license_state:{self._tenant_id}"


def _parse_moment(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


__all__ = ["STATE_FILE_NAME", "EncryptedLicenseStateStore", "default_state_dir"]
