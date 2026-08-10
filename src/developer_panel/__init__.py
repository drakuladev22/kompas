"""Developer Paneli — hazırlayıcının YERLİ aləti (spesifikasiya bölmə 8).

──────────────────────────────────────────────────────────────────────────────
BU PAKET MÜŞTƏRİ QURAŞDIRMASINDA İŞLƏMİR
──────────────────────────────────────────────────────────────────────────────
Panel internetə açıq vebsayt DEYİL — Supabase-ə birbaşa qoşulan, yalnız
hazırlayıcının öz kompüterində `--developer-mode` ilə açılan ayrı bir
rejimdir. Ayrıca server, VPS, domen və ya hostinq tələb ETMİR.

Paket `src/application` və ya `src/presentation` altında DEYİL, çünki o,
məhsulun bir hissəsi deyil: müştəri `.exe`-sinin qablaşdırılmasında bu
qovluq ümumiyyətlə daxil edilmir. Ayrı ad sahəsi bu sərhədi kodun
strukturunda görünən edir.
"""

from src.developer_panel.console import (
    confirmation_text,
    render_audit_trail,
    render_table,
    run_console,
)

__all__ = [
    "confirmation_text",
    "render_audit_trail",
    "render_table",
    "run_console",
]
