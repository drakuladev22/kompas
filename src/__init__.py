"""KompasOS — Enterprise Leave/POS/ERP/Task/Dashboard sistemi.

Layihə Domain-Driven Design prinsipi ilə qurulub:
    domain          — biznes qaydaları, entity-lər, value object-lər (heç bir xarici asılılıq)
    application     — use case-lər, orkestrasiya, DTO-lar
    infrastructure  — DB, ERP/1C, şifrələmə, bildirişlər (xarici dünya)
    presentation    — PySide6 GUI qatı
    shared          — cross-cutting: event bus, DI, saga, logger
"""

__version__ = "0.2.0"
__app_name__ = "KompasOS"
