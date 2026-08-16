"""Audit Jurnalının OXU yolu — süzgəc və səhifələmə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA KONTROLLER, NİYƏ `screen_data.py` DEYİL
──────────────────────────────────────────────────────────────────────────────
`screen_data.py` bir dəfəlik doldurmadır: `populate()` çağırılır, ekran dolur,
sessiya bağlanır. Audit ekranı isə istifadəçi hər süzgəc dəyişəndə və hər
səhifə düyməsində YENİDƏN oxumalıdır — bu dövrə `populate()`-ın tək
çağırışından uzun yaşayır. Layihədə eyni səbəblə `camera_queue.py`,
`fine_entry.py` və `root_control.py` öz kontrollerlərini daşıyır (CLAUDE.md
bölmə 6).

Ekran YALNIZ OXUYUR, lakin bu, onu `screen_data`-ya aid etmir: meyar
"yazırmı?" deyil, "təkrar oxuyurmu?"-dur.

──────────────────────────────────────────────────────────────────────────────
SÜZGƏC EKRANDAN GƏLİR, LİMİT ROOT-DAN
──────────────────────────────────────────────────────────────────────────────
Səhifə ölçüsü `AuditFilter.limit`-dədir və `search()` onu Root tavanı ilə
(`AUDIT_LOG_MAX_PAGE_SIZE`) kəsir. Kontroller tavanı ÖZÜ oxumur: iki tərəf
ayrı mənbədən oxusaydı, Root tavanı endirəndə ekran "18 səhifə" yazar, baza
isə başqa sayda sətir qaytarardı — səhifələmə düymələri mövcud olmayan
səhifəyə aparardı.

──────────────────────────────────────────────────────────────────────────────
BAXIŞ FAKTI DA AUDİT-LƏNİR
──────────────────────────────────────────────────────────────────────────────
`search()` özü baxışı jurnala yazır, ona görə hər oxuma `commit()` tələb edir
(bax `audit_query` başlığı). Commit unudulsaydı, kim jurnala baxdığı qeydi
sükutla itərdi — audit sisteminin ən həssas izlərindən biri.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.application.use_cases.audit_query import DEFAULT_PAGE_SIZE, AuditFilter
from src.domain.policies import SystemLimitKey
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_d import AuditScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Modul seçicisindəki "hamısı" bəndi — süzgəcə çevrilmir.
ALL_MODULES = "Bütün modullar"


def entry_row(entry: Any) -> dict[str, str]:
    """`AuditEntry` → ekranın gözlədiyi sətir.

    AÇARLAR MAKET YOLU İLƏ EYNİDİR (`preview_data.AUDIT_ENTRIES`): `time`,
    `user`, `action`, `module`, `detail`. Bu funksiya ORTAQ MƏNBƏDİR, çünki
    ilkin doldurma (`screen_data`) və süzülmüş oxuma (bu kontroller) eyni
    formanı verməlidir — iki yerdə ayrı-ayrı yazılsaydı, biri düzələndə
    digəri arxada qalardı və fərq yalnız istehsalatda görünərdi.
    """
    occurred = getattr(entry, "occurred_at", None)
    return {
        "time": occurred.strftime("%d.%m %H:%M") if occurred is not None else "",
        "user": getattr(entry, "actor_name", "") or "",
        "action": getattr(entry, "action", "") or "",
        "module": getattr(entry, "entity_type", "") or "",
        "detail": getattr(entry, "reason", "") or "",
    }


class AuditLogController:
    """Audit ekranının `filters_changed` / `page_changed` siqnallarını bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: Cari süzgəc — səhifə dəyişəndə ŞƏRTLƏR QORUNUR. Səhifə düyməsi
        #: süzgəci sıfırlasaydı, istifadəçi 2-ci səhifəyə keçəndə tamam başqa
        #: dəst görər və səbəbini anlamazdı.
        self._filters: dict[str, Any] = {}
        self._page = 1

    def attach(self, screen: AuditScreen) -> None:
        screen.filters_changed.connect(lambda values: self._on_filters(screen, values))
        screen.page_changed.connect(lambda page: self._on_page(screen, page))

    # ------------------------------- hadisələr ------------------------------- #

    def _on_filters(self, screen: AuditScreen, values: dict[str, Any]) -> None:
        """Süzgəc dəyişdi — HƏMİŞƏ birinci səhifəyə qayıdılır.

        Səhifə saxlanılsaydı, 7-ci səhifədə dar bir süzgəc seçən istifadəçi
        boş ekran görərdi (nəticə 2 səhifədir) və bunu "nəticə yoxdur" kimi
        oxuyardı — halbuki nəticə var, sadəcə başqa səhifədədir.
        """
        self._filters = dict(values)
        self._page = 1
        self._reload(screen)

    def _on_page(self, screen: AuditScreen, page: int) -> None:
        self._page = max(1, int(page))
        self._reload(screen)

    # ------------------------------- oxuma ----------------------------------- #

    def _reload(self, screen: AuditScreen) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                page = self._search(session)
                session.commit()  # baxış faktı da audit-lənir
        except KompasOSError as exc:
            # SÜKUT QADAĞANDIR: istifadəçi düyməni basıb və nəticə gözləyir.
            _error_log.exception("AUDIT_FILTER_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Audit jurnalı oxuna bilmədi",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )
            return

        rows = [entry_row(entry) for entry in page.entries]
        screen.set_entries(rows, result_text=f"{page.total} nəticədən {len(rows)}")
        limit = max(1, page.filters.limit)
        total_pages = max(1, (page.total + limit - 1) // limit)
        screen.set_pagination(self._page, total_pages)

    def _search(self, session: Session) -> Any:
        use_case = session.audit_query
        # SƏHİFƏ ÖLÇÜSÜ ROOT-DANDIR: `DEFAULT_PAGE_SIZE` yalnız fallback-dır
        # (həqiqi mənbə `system_limits.AUDIT_LOG_DEFAULT_PAGE_SIZE`). Tavanı
        # isə `search()` özü tətbiq edir — burada təkrar oxumaq iki mənbə
        # yaradardı.
        limit = session.limits.get_int(
            session.tenant_id,
            SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE.value,
            DEFAULT_PAGE_SIZE,
        )
        module = str(self._filters.get("module", "") or "")
        return use_case.search(
            tenant_id=session.tenant_id,
            actor=self._actor,
            filters=AuditFilter(
                search=str(self._filters.get("search", "") or ""),
                entity_type=None if module in {"", ALL_MODULES} else module,
                limit=limit,
                offset=(self._page - 1) * limit,
            ),
        )


__all__ = ["ALL_MODULES", "AuditLogController", "entry_row"]
