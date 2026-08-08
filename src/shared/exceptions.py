"""KompasOS üçün mərkəzləşdirilmiş istisna (exception) iyerarxiyası.

Bütün domen/infrastruktur istisnaları `KompasOSError`-dan törəyir ki, üst qatlar
(GUI shell, saga orkestratoru, global exception handler) tək bir tip üzərindən
tutub emal edə bilsin.
"""

from __future__ import annotations

from typing import Any


class KompasOSError(Exception):
    """Bütün KompasOS istisnalarının kök sinfi."""

    #: İstifadəçiyə göstərilə bilən, texniki-olmayan Azərbaycan dilində mesaj.
    user_message: str = "Gözlənilməz sistem xətası baş verdi."

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context or {}
        if user_message is not None:
            self.user_message = user_message

    def to_dict(self) -> dict[str, Any]:
        """Structured log-a yazmaq üçün serializasiya."""
        return {
            "error_type": type(self).__name__,
            "message": self.message,
            "user_message": self.user_message,
            "context": self.context,
        }


# --------------------------------------------------------------------------- #
# DI Container
# --------------------------------------------------------------------------- #
class DependencyNotRegisteredError(KompasOSError):
    """Tələb olunan asılılıq konteynerdə qeydiyyatdan keçməyib."""

    user_message = "Sistem komponenti yüklənə bilmədi. Administratorla əlaqə saxlayın."


class CircularDependencyError(KompasOSError):
    """Asılılıq qrafında dövr (cycle) aşkarlandı."""

    user_message = "Sistem konfiqurasiya xətası. Administratorla əlaqə saxlayın."


class DuplicateRegistrationError(KompasOSError):
    """Eyni tip artıq qeydiyyatdan keçib və `override=False`-dur."""

    user_message = "Sistem konfiqurasiya xətası. Administratorla əlaqə saxlayın."


# --------------------------------------------------------------------------- #
# Event Bus
# --------------------------------------------------------------------------- #
class EventHandlerError(KompasOSError):
    """Event handler icra zamanı uğursuz oldu."""

    user_message = "Əməliyyat qismən tamamlandı. Nəticəni yoxlayın."


# --------------------------------------------------------------------------- #
# Saga
# --------------------------------------------------------------------------- #
class SagaExecutionError(KompasOSError):
    """Saga addımı uğursuz oldu, kompensasiya işə düşdü."""

    user_message = "Əməliyyat tamamlanmadı və geri qaytarıldı. Yenidən cəhd edin."


class SagaCompensationError(KompasOSError):
    """Kompensasiya özü uğursuz oldu → PENDING_RECONCILIATION.

    Bu, sistemin ən ciddi məlumat-bütövlüyü vəziyyətidir (bax spesifikasiya
    bölmə 1 və bölmə 7): heç vaxt sükutla qeyd olunmamalı, mütləq e-poçt
    fallback kanalı ilə admin-ə bildirilməlidir.
    """

    user_message = (
        "Əməliyyat yarımçıq qaldı və avtomatik bərpa alınmadı. Bu hadisə administratora bildirildi."
    )


# --------------------------------------------------------------------------- #
# Security / Encryption
# --------------------------------------------------------------------------- #
class EncryptionKeyError(KompasOSError):
    """Fernet master açarı tapılmadı, yararsızdır və ya rotasiya xətası."""

    user_message = "Təhlükəsizlik açarı konfiqurasiya edilməyib. Administratorla əlaqə saxlayın."


class DecryptionError(KompasOSError):
    """Şifrə açma uğursuz oldu (yanlış açar və ya korlanmış məlumat)."""

    user_message = "Şifrələnmiş məlumat oxuna bilmədi."


# --------------------------------------------------------------------------- #
# Konfiqurasiya
# --------------------------------------------------------------------------- #
class ConfigurationError(KompasOSError):
    """Zəruri konfiqurasiya dəyəri yoxdur və ya yanlışdır."""

    user_message = "Sistem konfiqurasiyası natamamdır. Administratorla əlaqə saxlayın."
