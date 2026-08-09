"""Maketdən götürülmüş ölçülər — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI MODUL, NİYƏ `tokens.py`-DA DEYİL
──────────────────────────────────────────────────────────────────────────────
`tokens.py`-dakı `METRICS` ümumi şkaladır (4/8/16/24/32) və QSS-ə token kimi
ötürülür. Buradakı dəyərlər isə KONKRET maket ölçüləridir — 226px sol panel,
62px başlıq zolağı, 38px pəncərə başlığı, 40px naviqasiya sətri. Onlar şkalaya
düşmür və QSS tokeni də deyil: Python tərəfdə `setFixedWidth`, `setSpacing`,
`setContentsMargins` çağırışlarında işlənir.

İkisini qarışdırmaq `tokens.py`-ın müqaviləsini pozardı: `check_contrast.py`
həmin faylı izolyasiya ilə `exec` edir və orada "226" kimi bir dəyər rəng
lüğətinə düşsəydi, yoxlayıcı onu rəng kimi oxumağa çalışardı.

Hər sabitin yanındakı şərh onun maketdəki mənbəyini göstərir.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------- #
# Pəncərə
# --------------------------------------------------------------------------- #

#: Spesifikasiyanın minimum pəncərə ölçüsü (bölmə "PLATFORMA QAYDALARI").
WINDOW_MIN_WIDTH: Final = 1280
WINDOW_MIN_HEIGHT: Final = 800

#: Custom title bar hündürlüyü — maketdə `height: 38px`.
TITLEBAR_HEIGHT: Final = 38
#: Loqo kvadratı — `width/height: 16px; border-radius: 5px`.
TITLEBAR_LOGO_SIZE: Final = 16
#: Pəncərə düymələrinin eni (—, □, ×).
WINDOW_BUTTON_WIDTH: Final = 46

# --------------------------------------------------------------------------- #
# Sol naviqasiya
# --------------------------------------------------------------------------- #

#: `width: 226px` — maketin bütün admin ekranlarında eynidir.
SIDEBAR_WIDTH: Final = 226
#: Daraldılmış rejim (yalnız ikonlar) — spesifikasiya "daralda bilər" deyir.
SIDEBAR_COLLAPSED_WIDTH: Final = 64
#: `padding: 20px 12px`.
SIDEBAR_PADDING_V: Final = 20
SIDEBAR_PADDING_H: Final = 12
#: Maddələr arası `gap: 4px`.
SIDEBAR_ITEM_SPACING: Final = 4
#: Maddə hündürlüyü `height: 40px`.
NAV_ITEM_HEIGHT: Final = 40
#: İkon ilə mətn arası `gap: 11px`.
NAV_ITEM_ICON_SPACING: Final = 11
#: Bölmə başlığının alt boşluğu `padding: 0 12px 10px`.
SIDEBAR_LABEL_BOTTOM: Final = 10

# --------------------------------------------------------------------------- #
# Səhifə başlığı (header)
# --------------------------------------------------------------------------- #

#: `height: 62px`.
HEADER_HEIGHT: Final = 62
#: `padding: 0 26px`.
HEADER_PADDING_H: Final = 26
#: Başlıq ilə alt-başlıq arası `gap: 14px`.
HEADER_SPACING: Final = 14
#: Header-dəki dairəvi/kvadrat ikon düymələri `34×34`.
HEADER_ICON_BUTTON: Final = 34
#: İstifadəçi avatarı `32×32`.
AVATAR_SIZE: Final = 32

# --------------------------------------------------------------------------- #
# Kontent
# --------------------------------------------------------------------------- #

#: `padding: 22px 26px`.
CONTENT_PADDING_V: Final = 22
CONTENT_PADDING_H: Final = 26
#: Alt boşluq — üzən dəstək düyməsi (54px) + kənar məsafəsi (28px) +
#: nəfəs payı. Məzmun onun altında qalmasın deyə.
CONTENT_BOTTOM_SAFE_AREA: Final = 96
#: Kartlar arası `gap: 18px`.
CARD_SPACING: Final = 18
#: Kart daxili `padding: 16px 20px` (siyahı sətri) / `18px` (adi kart).
CARD_PADDING: Final = 18
#: Dashboard widget sətri `grid-auto-rows: 132px`.
DASHBOARD_ROW_HEIGHT: Final = 132

# --------------------------------------------------------------------------- #
# Ümumi komponentlər
# --------------------------------------------------------------------------- #

#: Status nöqtəsi `width/height: 8px`.
STATUS_DOT_SIZE: Final = 8
#: Boş/xəta vəziyyətindəki iri ikon çərçivəsi `76×76, radius 22`.
STATE_ICON_BOX: Final = 76
STATE_ICON_BOX_RADIUS: Final = 22
#: Həmin çərçivədəki ikon `32×32`.
STATE_ICON_SIZE: Final = 32
#: Boş vəziyyət mətninin maksimum eni `max-width: 440px`.
STATE_TEXT_MAX_WIDTH: Final = 440
#: Bildiriş paneli `width: 420px`.
NOTIFICATION_PANEL_WIDTH: Final = 420
#: Dəstək chat paneli `372×486`.
SUPPORT_PANEL_WIDTH: Final = 372
SUPPORT_PANEL_HEIGHT: Final = 486
#: Dəstək düyməsi (FAB) `54×54`.
SUPPORT_FAB_SIZE: Final = 54
#: Detal paneli (developer, ERP) `width: 400px`.
DETAIL_PANEL_WIDTH: Final = 400

# --------------------------------------------------------------------------- #
# Kiosk (PIN / işçi ekranı)
# --------------------------------------------------------------------------- #

#: PIN indikator dairəsi.
PIN_DOT_SIZE: Final = 18
#: 3×4 klaviatura düyməsi — toxunma hədəfi (bölmə 9: minimum 44px).
KEYPAD_BUTTON_SIZE: Final = 88
#: Mətn düymələri ('Təmizlə', 'Sil') — etiket kvadrata sığmır.
KEYPAD_TEXT_BUTTON_WIDTH: Final = 124
KEYPAD_SPACING: Final = 16

# --------------------------------------------------------------------------- #
# Tipoqrafiya (maketdəki konkret ölçülər)
# --------------------------------------------------------------------------- #
# `tokens.py`-dakı şkala 11/13/15/19/26-dır; maket aralıq dəyərlər də işlədir
# (13.5px naviqasiya, 12.5px köməkçi mətn). Qt tam ədəd gözlədiyi üçün
# yuvarlaqlaşdırılır — fərq gözlə seçilmir, lakin mənbə burada qeyd olunur.

#: Naviqasiya maddəsi — maketdə 13.5px.
FONT_NAV_ITEM: Final = 13
#: Səhifə başlığı — 17px.
FONT_PAGE_TITLE: Final = 17
#: Köməkçi/solğun mətn — 12.5px.
FONT_CAPTION: Final = 12
#: Bölmə etiketi (böyük hərflər) — 11px.
FONT_SECTION_LABEL: Final = 11
#: Boş vəziyyət başlığı — 20px.
FONT_STATE_TITLE: Final = 20
#: Kiosk başlığı — 28px.
FONT_KIOSK_TITLE: Final = 28

#: Bölmə etiketindəki hərf aralığı — maketdə `letter-spacing: 0.12em`.
#: QSS bunu dəstəkləmir, `QFont.setLetterSpacing` ilə verilir (piksel olaraq).
SECTION_LABEL_LETTER_SPACING: Final = 1.3

__all__ = [name for name in dir() if name.isupper()]
