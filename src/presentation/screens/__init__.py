"""Modul ekranları (maket Qrup A–G, 27 ekran) — Faza 4.2.

base           — ekran bazası və vəziyyət keçidi (boş/yüklənir/xəta)
group_a_entry  — 01 Splash · 02 İlk Quraşdırma · 03 Admin Girişi
group_a_kiosk  — 04 PIN Klaviaturası · 05 İşçi Ana Ekranı
group_b        — 06 Canlı Növbə · 07 Vaxt Düzəlişi · 08 Cərimə Qeydiyyatı
group_c        — 09 Dashboard · 10 İcazə Matrisi · 11 İstifadəçilər ·
                 12 Növbə Planlama · 13 Gündəlik Tabel · 14 Növbə Dəyişmə
group_d        — 15 ERP/1C · 16 Backup · 17 Diaqnostika · 18 Audit ·
                 19 Ayarlar · 20 ROOT Control Center
group_e        — 21 Dəstək Chat · 22 Developer Panel · 23 LICENSE_INACTIVE
group_f        — 24 Tapşırıqlar · 25 Satış Xalları · 26 Etirazlar ·
                 27 Şübhəli Satışlar
group_g        — 29 Bildiriş Mərkəzi · 30 Profil
                 (28 — vəziyyətlər — `base.ContentSwitcher`-dədir)
"""

from src.presentation.screens.base import ContentSwitcher, Screen

__all__ = ["ContentSwitcher", "Screen"]
