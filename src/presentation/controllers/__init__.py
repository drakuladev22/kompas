"""Kontroller qatı — ekran ↔ use case körpüsü — Faza 5.

Burada İŞ MƏNTİQİ YOXDUR. Hər kontroller üç şey edir:

    1. ekranın verdiyi sadə dəyərləri use case-in gözlədiyi tiplərə çevirir,
    2. use case-i çağırır,
    3. nəticəni (və domen istisnalarını) ekranın göstərə biləcəyi formaya salır.

Bu ayrılıq olmasa, ya Qt kodu domen istisnalarını tutmalı olardı (ekran
qaydaları bilməli olardı), ya da use case istifadəçi mətni qaytarmalı olardı
(domen dil qatına bağlanardı).
"""

from src.presentation.controllers.auth import AuthController, AuthOutcome
from src.presentation.controllers.root_control import RootControlController

__all__ = ["AuthController", "AuthOutcome", "RootControlController"]
