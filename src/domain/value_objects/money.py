"""Pul value object-i (AZN).

QAYDA: pul HEÇ VAXT `float` ilə təmsil olunmur. `0.1 + 0.2 != 0.3` problemi
cərimə/premiya hesablamasında real maliyyə səhvinə çevrilir. `Decimal` +
açıq yuvarlaqlaşdırma siyasəti istifadə olunur.

DB tərəfi: `NUMERIC(10, 2)` — 2 onluq rəqəm, maksimum 99,999,999.99 AZN.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

from src.shared.exceptions import KompasOSError

CURRENCY_CODE: Final[str] = "AZN"
DECIMAL_PLACES: Final[int] = 2
QUANTUM: Final[Decimal] = Decimal("0.01")
#: DB-dəki NUMERIC(10, 2) limiti.
MAX_AMOUNT: Final[Decimal] = Decimal("99999999.99")


class InvalidMoneyError(KompasOSError):
    """Pul dəyəri yararsızdır."""

    user_message = "Məbləğ düzgün deyil."


@dataclass(frozen=True, order=True)
class Money:
    """AZN məbləği — dəyişməz, mənfi ola bilər (korreksiya/geri qaytarma üçün).

    Yuvarlaqlaşdırma `ROUND_HALF_UP` ilə edilir (mühasibatlıq konvensiyası;
    Python-un defolt `ROUND_HALF_EVEN`-i "bankçı yuvarlaqlaşdırması"dır və
    əl ilə hesablayan mühasibin nəticəsi ilə uyğun gəlməyə bilər).
    """

    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise InvalidMoneyError(
                f"Məbləğ Decimal olmalıdır, alındı: {type(self.amount).__name__} "
                f"(float pul üçün QADAĞANDIR)"
            )
        if self.amount.is_nan() or self.amount.is_infinite():
            raise InvalidMoneyError("Məbləğ ədəd olmalıdır")
        if abs(self.amount) > MAX_AMOUNT:
            raise InvalidMoneyError(
                f"Məbləğ {MAX_AMOUNT} AZN limitini aşır",
                context={"amount": str(self.amount)},
            )
        # Frozen dataclass — normallaşdırılmış dəyəri object.__setattr__ ilə yazırıq.
        object.__setattr__(self, "amount", self.amount.quantize(QUANTUM, rounding=ROUND_HALF_UP))

    # ------------------------------ yaradıcılar ----------------------------- #

    @classmethod
    def zero(cls) -> Money:
        return cls(Decimal("0.00"))

    @classmethod
    def parse(cls, raw: str | int | Decimal) -> Money:
        """Mətn/tam ədəddən məbləğ yaradır. `float` QƏSDƏN qəbul edilmir.

        Tip yoxlayıcısı `float`-u onsuz da bloklayır, lakin işləmə zamanı da
        yoxlanılır — məlumat DB/JSON kimi tipsiz mənbədən gələ bilər.
        """
        if isinstance(raw, float):
            raise InvalidMoneyError(
                "float pul dəyəri üçün QADAĞANDIR — mətn və ya Decimal istifadə edin"
            )
        try:
            return cls(Decimal(str(raw).strip().replace(",", ".")))
        except (InvalidOperation, ValueError) as exc:
            raise InvalidMoneyError(f"Məbləğ oxuna bilmədi: {raw!r}") from exc

    # -------------------------------- riyazi -------------------------------- #

    def __add__(self, other: Money) -> Money:
        return Money(self.amount + other.amount)

    def __sub__(self, other: Money) -> Money:
        return Money(self.amount - other.amount)

    def __neg__(self) -> Money:
        return Money(-self.amount)

    def multiply(self, factor: int | Decimal) -> Money:
        """Tam ədədə və ya `Decimal`-a vurur (məs. `2 × Delay` düsturu)."""
        if isinstance(factor, float):
            raise InvalidMoneyError("float vuruq QADAĞANDIR — Decimal istifadə edin")
        return Money(self.amount * Decimal(factor))

    # ------------------------------ yoxlamalar ------------------------------ #

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def require_non_negative(self, *, field: str = "məbləğ") -> Money:
        """Cərimə/mükafat kimi mənfi ola bilməyən sahələr üçün qoruyucu."""
        if self.is_negative:
            raise InvalidMoneyError(
                f"{field} mənfi ola bilməz: {self.amount}",
                user_message=f"{field.capitalize()} mənfi ola bilməz.",
            )
        return self

    # ------------------------------- göstərmə ------------------------------- #

    def format_az(self) -> str:
        """İstifadəçi interfeysi üçün: `12.50 AZN`."""
        return f"{self.amount:.{DECIMAL_PLACES}f} {CURRENCY_CODE}"

    def __str__(self) -> str:
        return self.format_az()

    def __repr__(self) -> str:
        return f"Money({self.amount})"


__all__ = ["CURRENCY_CODE", "MAX_AMOUNT", "InvalidMoneyError", "Money"]
