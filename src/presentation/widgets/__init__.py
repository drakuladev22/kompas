"""Dizayn sistemi komponentləri (Qrup A–G maketlərindən) — Faza 4.2.

Modul xəritəsi:

    metrics      — maketdən götürülmüş ölçülər (226px panel, 62px header, …)
    icons        — xətt-əsaslı SVG ikon dəsti, rəng vəziyyətə görə verilir
    primitives   — kart, nişan, status nöqtəsi, avatar, ayırıcı, skeleton
    buttons      — action / secondary / icon / nav / window düymə variantları
    title_bar    — çərçivəsiz pəncərənin öz başlıq zolağı
    sidebar      — sol naviqasiya (icazəyə görə süzülmüş maddələri göstərir)
    page_header  — 62px səhifə başlığı + bildiriş zəngi
    states       — boş / yüklənmə / xəta vəziyyətləri (Qrup G qaydası)
    data_table   — başlıq + kart içində sətirlər
    safe_text    — tooltip mətninin HTML kimi şərh olunmasının qarşısı

İdxal qaydası: ekranlar bu paketdən idxal edir, əks istiqamət YOXDUR —
komponent heç bir ekranı tanımır.
"""

from src.presentation.widgets import icons, metrics
from src.presentation.widgets.buttons import (
    NavButton,
    WindowButton,
    action_button,
    icon_button,
    secondary_button,
)
from src.presentation.widgets.data_table import Column, DataTable, TableRow
from src.presentation.widgets.page_header import NotificationBell, PageHeader
from src.presentation.widgets.primitives import (
    Avatar,
    Card,
    Chip,
    ChipTone,
    Divider,
    Skeleton,
    StatusDot,
    body_label,
    column,
    mono_label,
    muted_label,
    row,
    section_label,
    stretch,
    title_label,
)
from src.presentation.widgets.sidebar import Sidebar
from src.presentation.widgets.states import (
    EmptyState,
    ErrorState,
    LoadingState,
    StateIconBox,
)
from src.presentation.widgets.title_bar import TitleBar

__all__ = [
    "Avatar",
    "Card",
    "Chip",
    "ChipTone",
    "Column",
    "DataTable",
    "Divider",
    "EmptyState",
    "ErrorState",
    "LoadingState",
    "NavButton",
    "NotificationBell",
    "PageHeader",
    "Sidebar",
    "Skeleton",
    "StateIconBox",
    "StatusDot",
    "TableRow",
    "TitleBar",
    "WindowButton",
    "action_button",
    "body_label",
    "column",
    "icon_button",
    "icons",
    "metrics",
    "mono_label",
    "muted_label",
    "row",
    "secondary_button",
    "section_label",
    "stretch",
    "title_label",
]
