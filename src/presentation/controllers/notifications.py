"""Bildiriş panelinin CANLI yolu — header zəngi + «oxundu» işarəsi (bölmə 7).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screen_data.py` DEYİL, AYRICA KONTROLLER
──────────────────────────────────────────────────────────────────────────────
Panel yalnız oxumur — sətrə klik və «Hamısını oxunmuş et» `notifications.read_at`
sahəsini YAZIR. Yazıdan sonra siyahı və header nişanı yenidən oxunmalıdır; bu
dövrə `populate()`-ın tək çağırışından uzun yaşayır. Layihədə eyni səbəbdən
`fine_entry.py`, `camera_queue.py` və `drive_connection.py` da ayrıca
kontrollerdir.

──────────────────────────────────────────────────────────────────────────────
SESSİYA SAXLANMIR
──────────────────────────────────────────────────────────────────────────────
Hər əməliyyat üçün yeni sessiya açılır və commit edilir. Panel saatlarla açıq
qala bilər; uzun-ömürlü tranzaksiya bu müddət boyu kilid saxlayardı və
`SET LOCAL` konteksti də köhnəlmiş bağlantıya bağlı qalardı.

Kontrollerə istinad da saxlanmır: o, siqnallara bağladığı `lambda`-ların
bağlamasında yaşayır və örtüklə birlikdə ölür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AUDİT YAZISI YOXDUR
──────────────────────────────────────────────────────────────────────────────
`audit_logs` biznes/təhlükəsizlik hadisələrinin izidir (bölmə 3/4/7).
Bildirişə klik heç bir vəziyyəti dəyişmir — nə pul, nə status, nə səlahiyyət;
`read_at` sırf interfeys nişanıdır. Hər zəng açılışını audit-ləsəydik jurnal
gündə yüzlərlə mənasız sətirlə dolar və HƏQİQİ audit sətirləri həmin
səs-küydə itərdi.

──────────────────────────────────────────────────────────────────────────────
XƏTA PANELİ BOŞ QOYUR, ÖRTÜYÜ ÇÖKDÜRMÜR
──────────────────────────────────────────────────────────────────────────────
`screen_data.populate()` ilə eyni istiqamət: baza əlçatmazdırsa zəng nişanı
boş qalır, səbəb `error.log`-a düşür. Bildirişin gəlməməsi işi dayandırmır,
lakin örtüyün çökməsi dayandırardı.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.notifications import hidden_tenant_categories
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.infrastructure.persistence.notification_repositories import NotificationRow
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_g import NotificationPanel
    from src.presentation.widgets.page_header import PageHeader

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Kateqoriya → sətir ikonu (`group_g._NOTIFICATION_KINDS` açarları).
#: Bu, iş qaydası deyil, YALNIZ görünüş seçimidir: eyni paneldə "1C bağlantısı
#: kəsildi" ilə "növbə dəyişikliyi təsdiqləndi" eyni tonda görünsəydi,
#: istifadəçi hansına dərhal baxmalı olduğunu ayırd edə bilməzdi.
_KIND_BY_CATEGORY: Final[dict[str, str]] = {
    # Sistemin işini dayandıran və ya pul/lisenziya toxunan hallar.
    "LICENSE_INACTIVE": "error",
    "PAYMENT_REMINDER": "error",
    "SAGA_PENDING_RECONCILIATION": "error",
    "ERP_SYNC_FAILED": "error",
    "DUAL_CONTROL_DEADLOCK_RISK": "error",
    "EMERGENCY_ACCESS_RECOVERY": "error",
    # Gözləyən/gecikən təsdiqlər — vaxt həssasdır, lakin sistem işləyir.
    "TIMEOUT_ESCALATION": "warning",
    "VERIFICATION_TIMEOUT": "warning",
    "CHECK_IN_TIMEOUT": "warning",
    "DUAL_CONTROL_PENDING": "warning",
    "TASK_DEADLINE": "warning",
    "DRIVE_QUOTA": "warning",
    "MONTHLY_LEAVE_LIMIT_EXCEEDED": "warning",
    "ATTENDANCE_SHEET_MISMATCH": "warning",
    "SHIFT_CHANGE_CONFLICT": "warning",
    # Baş vermiş və bağlanmış hadisələr.
    "FINE_APPEAL_DECIDED": "success",
    "SHIFT_SWAP_DECIDED": "success",
    "MONTHLY_FINES_PUBLISHED": "success",
}

#: «Təsdiq» süzgəcinə düşən kateqoriyalar. Maketdə üç çip var (Hamısı / Təsdiq
#: / Sistem), yəni bölgü İKİ qovluqludur: insan qərarı gözləyən (və ya verilmiş
#: qərarı bildirən) sətirlər «Təsdiq»dədir, qalanı «Sistem».
_APPROVAL_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "TIMEOUT_ESCALATION",
        "VERIFICATION_TIMEOUT",
        "CHECK_IN_TIMEOUT",
        "CHECK_IN_REJECTED",
        "DUAL_CONTROL_PENDING",
        "FINE_APPEAL_PENDING",
        "FINE_APPEAL_DECIDED",
        "SHIFT_SWAP_PENDING",
        "SHIFT_SWAP_DECIDED",
        "SHIFT_CHANGE_CONFLICT",
        "LEAVE_DECISION",
        "TASK_DEADLINE",
    }
)


class NotificationsController:
    """Zəng siqnalını canlı sorğuya, panel siqnallarını yazıya bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, panel: NotificationPanel, header: PageHeader) -> None:
        """Paneli və header nişanını canlı mənbəyə bağlayır.

        `bell_clicked`-a qoşulma `app.py`-dakı `_toggle_notifications`-DAN SONRA
        baş verir (bax `_install_overlays` şərhi): Qt birbaşa slotları qoşulma
        sırası ilə çağırır, yəni bura çatanda panelin görünürlüyü ARTIQ
        dəyişib və biz yalnız AÇILIŞDA sorğu göndəririk. Əks halda hər
        bağlanış da lazımsız bir sorğu demək olardı.
        """
        header.bell_clicked.connect(lambda: self._on_bell(panel, header))
        panel.notification_clicked.connect(
            lambda raw: self._on_clicked(raw, panel=panel, header=header)
        )
        panel.mark_all_read_requested.connect(lambda: self._on_mark_all(panel, header))
        # İlk oxunuş girişdən DƏRHAL sonra: zəng nişanı istifadəçi ona
        # toxunmadan ƏVVƏL doğru rəqəmi göstərməlidir — bildirişin bütün
        # məqsədi diqqət çəkməkdir, tapılmaq deyil.
        self.refresh(panel, header)

    def refresh(self, panel: NotificationPanel, header: PageHeader) -> None:
        """Siyahını və oxunmamış sayğacını yenidən oxuyur."""
        rows = self._load()
        now = datetime.now(UTC)
        panel.set_notifications([_to_item(row, now=now) for row in rows])
        # Sayğac EYNİ siyahıdan hesablanır: paneldəki «N yeni» çipi ilə header
        # nişanının fərqli rəqəm göstərməsi istifadəçidə "hansı doğrudur"
        # sualı yaradardı. Ayrıca `COUNT(*)` sorğusu daha dəqiq olardı, lakin
        # limit-dən artıq sətir praktikada yalnız uzun fasilədən sonra olur.
        header.set_unread(sum(1 for row in rows if row.is_unread))

    # ------------------------------- siqnallar ------------------------------- #

    def _on_bell(self, panel: NotificationPanel, header: PageHeader) -> None:
        if not panel.isVisible():
            return
        self.refresh(panel, header)

    def _on_clicked(self, raw_id: str, *, panel: NotificationPanel, header: PageHeader) -> None:
        """Sətrə klik = həmin bildiriş oxunmuş sayılır.

        Açar ekrandan gəlir və bizim öz sətirlərimizdəndir; yenə də UUID-yə
        çevrilmə qorunur — yararsız açar `ValueError` ilə örtüyü çökdürməməli,
        izi isə qalmalıdır.
        """
        try:
            notification_id = uuid.UUID(raw_id)
        except ValueError:
            _error_log.warning("NOTIFICATION_ID_INVALID", extra={"value": raw_id})
            return
        hidden = hidden_categories_for(self._actor)
        self._write(
            lambda repository: repository.mark_read(
                notification_id, self._actor.id, hidden_categories=hidden
            )
        )
        self.refresh(panel, header)

    def _on_mark_all(self, panel: NotificationPanel, header: PageHeader) -> None:
        hidden = hidden_categories_for(self._actor)
        self._write(
            lambda repository: repository.mark_all_read(self._actor.id, hidden_categories=hidden)
        )
        self.refresh(panel, header)

    # ------------------------------- baza yolu ------------------------------- #

    def _load(self) -> list[NotificationRow]:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                rows: list[NotificationRow] = session.notifications.list_for_recipient(
                    self._actor.id,
                    hidden_categories=hidden_categories_for(self._actor),
                )
                return rows
        except Exception:
            _error_log.exception("NOTIFICATIONS_LOAD_FAILED")
            return []

    def _write(self, operation: Any) -> None:
        """Bir yazı + commit. Uğursuzluq paneli çökdürmür, iz qoyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                operation(session.notifications)
                session.commit()
        except Exception:
            _error_log.exception("NOTIFICATION_READ_MARK_FAILED")


def hidden_categories_for(actor: Employee) -> frozenset[str]:
    """Aktorun görməyəcəyi tenant səviyyəli kateqoriyalar (bölmə 7).

    Qayda domendədir (`TENANT_NOTIFICATION_AUDIENCE`); burada yalnız aktorun
    EFFEKTİV icazələri predikata çevrilir — `has_permission` fərdi override-ı
    da nəzərə alır, yəni Root bir işçiyə müvəqqəti `can_approve_shift_swap`
    versə, həmin işçi növbə sorğusu bildirişini DƏRHAL görür.

    Funksiya kontrollerin İÇİNDƏ deyil, modul səviyyəsindədir: eyni süzgəc
    `screen_data._critical_notifications`-a da lazımdır və iki yerdə iki cür
    hesablansaydı, İdarə Panelindəki kritik siyahı ilə zəng nişanı fərqli
    dəst göstərərdi.
    """
    now = datetime.now(UTC)
    return hidden_tenant_categories(lambda flag: actor.has_permission(flag, now=now))


# --------------------------------------------------------------------------- #
# Sətir → panel formatı
# --------------------------------------------------------------------------- #


def _to_item(row: NotificationRow, *, now: datetime) -> dict[str, str]:
    """`NotificationPanel.set_notifications()`-in gözlədiyi sözlük.

    Açarlar `NotificationItem`-in FAKTİKİ oxuduqlarıdır: `id`, `kind`,
    `category`, `title`, `body`, `time`, `unread`. Maket yolu
    (`preview_data.NOTIFICATIONS`) də məhz bu açarları işlədir — iki yolun
    ad məkanı ayrılsaydı, uyğunsuzluq yalnız istehsalatda üzə çıxardı
    (bax `shell/menu.py` başlığı).
    """
    return {
        "id": str(row.id),
        "kind": _kind_of(row),
        "category": "approval" if row.category in _APPROVAL_CATEGORIES else "system",
        "title": row.title_az,
        "body": row.body_az,
        "time": _time_text(row.created_at, now=now),
        "unread": "1" if row.is_unread else "0",
    }


def _kind_of(row: NotificationRow) -> str:
    """Sətir ikonu — naməlum kateqoriya kritikliyə görə həll olunur.

    Fallback "info" DEYİL: siyahıda olmayan, lakin KRİTİK yazılmış bir
    kateqoriya (yeni modul əlavə edildikdə tamamilə mümkündür) adi məlumat
    sətri kimi görünsəydi, bölmə 7-nin "gözdən qaçmasın" məqsədi pozulardı.
    """
    known = _KIND_BY_CATEGORY.get(row.category)
    if known is not None:
        return known
    return "error" if row.is_critical else "info"


def _time_text(moment: datetime, *, now: datetime) -> str:
    """Maketdəki format: bu gün «09:58», dünən «Dünən 16:12», əvvəl «04.08 16:12».

    Tam tarix HƏMİŞƏ yazılmır: paneldəki sətirlərin əksəriyyəti bugünkündür və
    "12.08.2026 09:58" sətri kartın yerini boş yerə tutardı. Vaxt yerli zonaya
    çevrilir — istifadəçi UTC ilə işləmir.
    """
    local = moment.astimezone()
    today = now.astimezone().date()
    delta_days = (today - local.date()).days
    if delta_days <= 0:
        return f"{local:%H:%M}"
    if delta_days == 1:
        return f"Dünən {local:%H:%M}"
    return f"{local:%d.%m} {local:%H:%M}"


__all__ = ["NotificationsController", "hidden_categories_for"]
