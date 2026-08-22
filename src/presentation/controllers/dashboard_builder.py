"""Panel Qurucusunun YAZI yolu — `DashboardLayoutUseCase` (bölmə 6).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screen_data.py`-DA DEYİL
──────────────────────────────────────────────────────────────────────────────
Ekran hər toggle/sürüşdürmədə YAZIR (`user_preferences.dashboard_layout`,
miqrasiya 011) və yazıdan sonra siyahı yenidən oxunmalıdır: use case
icazəsiz/söndürülmüş modula aid açarları ATIR (`save()` içindəki süzgəc), yəni
ekranda qalan dəst yazılan dəstdən FƏRQLİ ola bilər. Bu dövrə `populate()`-ın
tək çağırışından uzun yaşayır (CLAUDE.md bölmə 6).

──────────────────────────────────────────────────────────────────────────────
BAXIŞ VƏ REDAKTƏ AYRI QAPILARDIR
──────────────────────────────────────────────────────────────────────────────
`view_for()` flag TƏLƏB ETMİR — hər istifadəçi öz düzülüşünü GÖRMƏLİDİR;
yalnız `save()`/`reset()` `can_edit_dashboard_widgets` istəyir (bax use case
`_require_edit_permission` docstring-i). Ona görə burada oxu və yazı fərqli
davranır: oxu uğursuz olsa ekran səbəblə boşalır, yazı uğursuz olsa ekran
QALIR və istifadəçi səbəbi görür — düzülüşü görə bilən, lakin dəyişə bilməyən
istifadəçi üçün ekranı tamamilə boşaltmaq məlumatı da əlindən alardı.

──────────────────────────────────────────────────────────────────────────────
HƏR ƏMƏLİYYAT ÖZ SESSİYASINDA
──────────────────────────────────────────────────────────────────────────────
Kontroller sessiyanı SAXLAMIR. Ekran açıq qaldıqca istifadəçi onlarla toggle
edə bilər; uzun-ömürlü tranzaksiya bu müddət boyu `user_preferences` sətrini
kilidli saxlayardı və eyni istifadəçinin başqa cihazdakı sessiyasını
bloklayardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_i import DashboardBuilderScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class DashboardBuilderController:
    """Qurucu ekranını `DashboardLayoutUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: DashboardBuilderScreen) -> None:
        screen.layout_changed.connect(lambda layout: self._on_layout_changed(screen, layout))
        screen.reset_requested.connect(lambda: self._on_reset(screen))
        self.refresh(screen)

    def refresh(self, screen: DashboardBuilderScreen) -> None:
        """Kataloqu və saxlanmış düzülüşü yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                view = session.dashboard_layout.view_for(
                    actor=self._actor, tenant_id=session.tenant_id
                )
                # `catalog_map()` `açar → (başlıq, izah)` verir — ekranın
                # FAKTİKİ gözlədiyi forma (`set_widgets(catalog, ...)`) və
                # maket yolunun (`preview_data.DASHBOARD_WIDGETS`) eynisi.
                #
                # `placements`/`columns` (audit G-5) EYNİ İMZANIN opsional
                # hissəsidir və maket yolu da onları ötürür — iki yolun ayrı
                # ad məkanı qurmasının qarşısı belə alınır (CLAUDE.md bölmə 6).
                screen.set_widgets(
                    view.catalog_map(),
                    order=list(view.order),
                    visible=set(view.visible),
                    placements=view.placement_map(),
                    columns=view.columns,
                )
        except KompasOSError as error:
            screen.show_error(title="Qurucu açıla bilmədi", message=error.user_message)
        except Exception:
            _error_log.exception("DASHBOARD_LAYOUT_LOAD_FAILED")
            screen.show_error(
                title="Qurucu açıla bilmədi",
                message="Düzülüş oxuna bilmədi. Yenidən cəhd edin.",
            )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_layout_changed(self, screen: DashboardBuilderScreen, layout: Any) -> None:
        """Ekranın yaydığı düzülüşü use case-ə ötürür.

        ELEMENTLƏR HƏM SADƏ AÇAR, HƏM DƏ KODLANMIŞ YERLƏŞDİRMƏ ola bilər
        (`"stat_tiles"` / `"stat_tiles@0,0,2"`) — `DashboardLayoutUseCase.save`
        hər ikisini oxuyur. Ona görə burada AYRIŞDIRMA YOXDUR: kontroller
        formatı bilməməlidir, əks halda format dəyişəndə üç yer (ekran,
        kontroller, use case) sinxron dəyişməli olardı.
        """
        entries = [str(item) for item in layout] if isinstance(layout, (list, tuple)) else []
        self._write(
            screen,
            lambda session: session.dashboard_layout.save(
                actor=self._actor, tenant_id=session.tenant_id, layout=entries
            ),
        )

    def _on_reset(self, screen: DashboardBuilderScreen) -> None:
        self._write(
            screen,
            lambda session: session.dashboard_layout.reset(
                actor=self._actor, tenant_id=session.tenant_id
            ),
        )

    def _write(self, screen: DashboardBuilderScreen, operation: Any) -> None:
        """Bir yazı + commit, sonra YENİDƏN OXU.

        Yenidən oxu məcburidir: `save()` icazəsiz açarları sükutla atır, yəni
        ekranda qalan dəst yazılandan fərqli ola bilər. Onu göstərməsək,
        istifadəçi gizlətdiyi bölmənin növbəti girişdə geri qayıtdığını görüb
        səbəbini tapa bilməzdi.

        ──────────────────────────────────────────────────────────────────────
        `on_retry` NİYƏ MƏCBURİDİR (QA-FULL FAZA 3 tapıntısı)
        ──────────────────────────────────────────────────────────────────────
        `refresh()` DƏRHAL burdan çağırılsaydı, `set_widgets()` → `_render()`
        → `show_content()` heç bir render arası olmadan bu banner-in
        ÜSTÜNDƏN yazardı (`sales_review.py`/`annual_leave.py` ilə eyni ailə)
        — VƏ DAHA PİSİ, `on_retry` verilmədən `show_error()` çağırmaq
        `base.py:442` qaydasınca "Yenidən Cəhd Et" düyməsini ÜMUMİYYƏTLƏ
        çəkmir. Layihə-boyu 15+ oxşar kontroller (`plugin_admin.py`,
        `annual_leave.py`, `catalog_admin.py`, …) `on_retry=lambda: self.
        refresh(screen)` ötürür — bu fayl YEGANƏ İSTİSNA idi. Modulun
        başlığındakı "düzülüş yenidən oxunub qaytarılır" iddiası da YALNIZ
        bununla doğrudur: xəta vəziyyəti QALIR, təzə oxu isə istifadəçinin
        «Yenidən Cəhd Et» kliki ilə baş verir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                operation(session)
                session.commit()
        except KompasOSError as error:
            # Ekran BOŞALDILMIR (bax modul başlığı) — səbəb xəta vəziyyətində
            # göstərilir, düzülüş isə `on_retry` ilə yenidən oxunur.
            screen.show_error(
                title="Düzülüş saxlanmadı",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception("DASHBOARD_LAYOUT_SAVE_FAILED")
            screen.show_error(
                title="Düzülüş saxlanmadı",
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
                on_retry=lambda: self.refresh(screen),
            )
            return

        self.refresh(screen)


__all__ = ["DashboardBuilderController"]
