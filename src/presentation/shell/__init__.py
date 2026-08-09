"""Role-driven Shell, NavigationRegistry render qatı — Faza 4.

window       — çərçivəsiz pəncərə bazası (öz başlıq zolağı, ölçü dəyişdirmə)
admin_shell  — sol panel + başlıq + kontent yığını
menu         — bütün menyu maddələrinin qeydiyyatı
kiosk        — tam ekran, çərçivəsiz kiosk pəncərəsi
"""

from src.presentation.shell.admin_shell import AdminShell
from src.presentation.shell.kiosk import KioskWindow
from src.presentation.shell.menu import DEFAULT_ENTRIES, build_default_registry
from src.presentation.shell.window import FramelessWindow

__all__ = [
    "DEFAULT_ENTRIES",
    "AdminShell",
    "FramelessWindow",
    "KioskWindow",
    "build_default_registry",
]
