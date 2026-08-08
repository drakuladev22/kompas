"""Konfiqurasiya edilə bilən biznes siyasətləri (spesifikasiya bölmə 3).

ROOT CONTROL CENTER-dəki `system_limits` dəyərləri burada tipləşdirilmiş
formada təqdim olunur. Domen qatı DB-ni tanımır — dəyərlər `SystemLimits`
portu (bax `interfaces.ports`) vasitəsilə ötürülür.

QAYDA: sistem limiti OLMAYAN sabit dəyər domen kodunda hardcode edilə bilməz
(bölmə 3, DİNAMİK LİMİT VƏ TAYMAUT İDARƏETMƏSİ) — istisna yalnız struktur
təhlükəsizlik zəmanətləridir (hardlock, anti-fraud, guard-lar).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Final

from src.domain.value_objects.money import Money


class SystemLimitKey(str, Enum):
    """`system_limits.limit_key` dəyərləri — DB seed-i ilə eyni."""

    MONTHLY_LEAVE_MINUTES_LIMIT = "MONTHLY_LEAVE_MINUTES_LIMIT"
    FINE_APPEAL_WINDOW_HOURS = "FINE_APPEAL_WINDOW_HOURS"
    LATE_TOLERANCE_MINUTES = "LATE_TOLERANCE_MINUTES"
    VERIFICATION_TIMEOUT_MINUTES = "VERIFICATION_TIMEOUT_MINUTES"
    DUAL_CONTROL_THRESHOLD_MINUTES = "DUAL_CONTROL_THRESHOLD_MINUTES"
    PIN_MAX_FAILED_ATTEMPTS = "PIN_MAX_FAILED_ATTEMPTS"
    PIN_LOCKOUT_MINUTES = "PIN_LOCKOUT_MINUTES"
    NTP_MAX_DRIFT_SECONDS = "NTP_MAX_DRIFT_SECONDS"
    MAX_UPLOAD_SIZE_BYTES = "MAX_UPLOAD_SIZE_BYTES"
    # --- BR-001 ilə əlavə olunanlar (bax aşağı) ---
    LEAVE_ALLOWANCE_SOURCE = "LEAVE_ALLOWANCE_SOURCE"
    LEAVE_ALLOWANCE_FIXED_MINUTES = "LEAVE_ALLOWANCE_FIXED_MINUTES"
    # --- BR-002 ilə əlavə olunan (bax aşağı) ---
    DELAY_FINE_RATE_PER_MINUTE = "DELAY_FINE_RATE_PER_MINUTE"


DEFAULT_LIMITS: Final[dict[SystemLimitKey, str]] = {
    SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT: "240",
    SystemLimitKey.FINE_APPEAL_WINDOW_HOURS: "72",
    SystemLimitKey.LATE_TOLERANCE_MINUTES: "15",
    SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES: "45",
    SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES: "30",
    SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS: "5",
    SystemLimitKey.PIN_LOCKOUT_MINUTES: "15",
    SystemLimitKey.NTP_MAX_DRIFT_SECONDS: "60",
    SystemLimitKey.MAX_UPLOAD_SIZE_BYTES: "5242880",
    SystemLimitKey.LEAVE_ALLOWANCE_SOURCE: "LEAVE_TYPE",
    SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES: "0",
    SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE: "0.00",
}


# --------------------------------------------------------------------------- #
# BR-001 — İcazə güzəşt müddətinin mənbəyi
# --------------------------------------------------------------------------- #


class LeaveAllowanceSource(str, Enum):
    """`Total = Requested + 2 × Delay` düsturundakı `Requested` haradan gəlir.

    ──────────────────────────────────────────────────────────────────────────
    BİZNES QƏRARI BR-001 (bax `docs/open_questions.md` OQ-001)
    ──────────────────────────────────────────────────────────────────────────
    Spesifikasiya bölmə 4-dəki iki düstur hərfi oxunuşda uyğun gəlmir:
    `Delay` "tam keçən vaxt" kimi təyin olunur, lakin `Total = Requested +
    2 × Delay` yalnız `Requested` bir MÜDDƏT olduqda mənalıdır.

    Eyni zamanda bölmə 4 deyir ki, İcazə Növü seçimi "düsturu DƏYİŞMİR".
    Bu iki tələb yalnız o halda uzlaşır ki, güzəşt müddətinin MƏNBƏYİ
    konfiqurasiya edilə bilən olsun — yəni Root qərar versin, kod yox.

    DEFOLT: `LEAVE_TYPE`. Səbəb: yalnız bu variantda 60 dəqiqəlik nahar
    fasiləsi "60 dəqiqə gecikmə" sayılmır. Əks halda aylıq 240 dəqiqəlik
    limit gündə iki fasilədən sonra dolar və sistem praktiki olaraq
    istifadəyə yararsız olar.
    ──────────────────────────────────────────────────────────────────────────
    """

    #: Güzəşt = seçilmiş İcazə Növünün standart müddəti (DEFOLT).
    LEAVE_TYPE = "LEAVE_TYPE"
    #: Güzəşt = `LEAVE_ALLOWANCE_FIXED_MINUTES` (növdən asılı olmayan tək dəyər).
    FIXED = "FIXED"
    #: Güzəşt yoxdur — spesifikasiyanın ən hərfi, ən sərt oxunuşu.
    NONE = "NONE"


@dataclass(frozen=True)
class LeaveAllowancePolicy:
    """Bir icazə sorğusu üçün güzəşt müddətini hesablayır."""

    source: LeaveAllowanceSource = LeaveAllowanceSource.LEAVE_TYPE
    fixed_minutes: int = 0

    def __post_init__(self) -> None:
        if self.fixed_minutes < 0:
            raise ValueError("Sabit güzəşt müddəti mənfi ola bilməz")

    def resolve(self, *, leave_type_minutes: int | None) -> int:
        """Güzəşt müddətini (dəqiqə) qaytarır.

        Args:
            leave_type_minutes: Seçilmiş İcazə Növünün standart müddəti.
                `None` (növ seçilməyib) → güzəşt 0.
        """
        if self.source is LeaveAllowanceSource.NONE:
            return 0
        if self.source is LeaveAllowanceSource.FIXED:
            return self.fixed_minutes
        return max(0, leave_type_minutes or 0)

    @classmethod
    def from_limits(cls, limits: dict[str, str]) -> LeaveAllowancePolicy:
        """`system_limits` lüğətindən qurur (naməlum dəyər → defolt)."""
        raw_source = limits.get(
            SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value,
            DEFAULT_LIMITS[SystemLimitKey.LEAVE_ALLOWANCE_SOURCE],
        )
        try:
            source = LeaveAllowanceSource(raw_source)
        except ValueError:
            source = LeaveAllowanceSource.LEAVE_TYPE

        raw_fixed = limits.get(
            SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES.value,
            DEFAULT_LIMITS[SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES],
        )
        try:
            fixed = max(0, int(raw_fixed))
        except (TypeError, ValueError):
            fixed = 0

        return cls(source=source, fixed_minutes=fixed)


# --------------------------------------------------------------------------- #
# BR-002 — Gecikmənin pul cəriməsinə çevrilməsi
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DelayFinePolicy:
    """Gecikmə dəqiqələrini AZN cəriməsinə çevirir.

    ──────────────────────────────────────────────────────────────────────────
    BİZNES QƏRARI BR-002
    ──────────────────────────────────────────────────────────────────────────
    Spesifikasiya `fines.source = AUTO_DELAY` cəriməsini və Premiya&Cərimə
    hesabatında "Premiyadan Tutulacaq Yekun Cərimə Məbləği (AZN)" sütununu
    tələb edir, LAKİN gecikmə DƏQİQƏLƏRİNİN AZN-ə necə çevrildiyini HEÇ YERDƏ
    göstərmir.

    QƏRAR: dərəcə (`DELAY_FINE_RATE_PER_MINUTE`) Root tərəfindən təyin olunur,
    **defolt 0.00 AZN**.

    Defolt 0 seçilib, çünki:
      * Təyin edilməmiş dərəcə ilə avtomatik pul kəsmək HÜQUQİ RİSKDİR —
        işçidən əsassız məbləğ tutula bilər.
      * 0 ilə sistem tam işləyir: gecikmə `Total` dəqiqə kimi aylıq 240
        dəqiqəlik limitdən çıxılır (spesifikasiyanın əsas mexanizmi), sadəcə
        ƏLAVƏ pul cəriməsi yaranmır.
      * Müştəri dərəcəni təyin edən kimi AUTO_DELAY cərimələri avtomatik
        işləməyə başlayır — kod dəyişikliyi lazım deyil.
    ──────────────────────────────────────────────────────────────────────────
    """

    rate_per_minute: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.rate_per_minute < 0:
            raise ValueError("Gecikmə cərimə dərəcəsi mənfi ola bilməz")

    @property
    def is_enabled(self) -> bool:
        """Dərəcə təyin edilibmi — `False` olduqda AUTO_DELAY cəriməsi yaranmır."""
        return self.rate_per_minute > 0

    def amount_for(self, delay_minutes: int) -> Money:
        """Gecikmə dəqiqələrinə görə cərimə məbləği."""
        if delay_minutes <= 0 or not self.is_enabled:
            return Money.zero()
        return Money(self.rate_per_minute * Decimal(delay_minutes))

    @classmethod
    def from_limits(cls, limits: dict[str, str]) -> DelayFinePolicy:
        raw = limits.get(
            SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE.value,
            DEFAULT_LIMITS[SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE],
        )
        try:
            rate = Decimal(str(raw).replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            rate = Decimal("0.00")
        return cls(rate_per_minute=max(Decimal("0.00"), rate))


# --------------------------------------------------------------------------- #
# Feature Toggle-lar (bölmə 3)
# --------------------------------------------------------------------------- #


class FeatureModule(str, Enum):
    """`feature_toggles.module_key` — DB seed-i ilə eyni."""

    CAMERA_VERIFICATION = "CAMERA_VERIFICATION"
    DUAL_CONTROL = "DUAL_CONTROL"
    SHIFT_SWAP = "SHIFT_SWAP"
    FINE_MODULE = "FINE_MODULE"
    TASK_ENGINE = "TASK_ENGINE"
    SALES_POINTS = "SALES_POINTS"
    DASHBOARD_BUILDER = "DASHBOARD_BUILDER"
    SUPPORT_CHAT = "SUPPORT_CHAT"

    @property
    def is_structural(self) -> bool:
        """Söndürülməsi əlavə xəbərdarlıq modalı tələb edən modul (bölmə 3).

        "Kamera Təsdiqi" STEP1-3 və Morning Check-in axınlarının struktur
        əsasıdır — bunu söndürmək adi bir-kliklik toggle DEYİL.
        """
        return self is FeatureModule.CAMERA_VERIFICATION


__all__ = [
    "DEFAULT_LIMITS",
    "DelayFinePolicy",
    "FeatureModule",
    "LeaveAllowancePolicy",
    "LeaveAllowanceSource",
    "SystemLimitKey",
]
