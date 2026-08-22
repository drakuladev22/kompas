"""Plugin İdarəetməsinin YAZI yolu — `PluginManagementUseCase` (bölmə 1).

──────────────────────────────────────────────────────────────────────────────
İMZA YOXLAMASI YAN KEÇİLMİR
──────────────────────────────────────────────────────────────────────────────
Quraşdırma `use_case.install(...)` üzərindən gedir və o, `verify()`-ı ÖN ŞƏRT
kimi icra edir (`plugin_management.py`). Kontroller nə imzanı özü yoxlayır, nə
də yoxlamanı "sonra" buraxır: paket faylı + manifest + imza sətri toplanır və
olduğu kimi ötürülür. Uğursuzluqda ORİJİNAL istisna mesajı göstərilir, çünki
o, imzanın NİYƏ rədd edildiyini deyir (naşir tanınmır / dayces uyğun gəlmir) —
onu "quraşdırılmadı" kimi ümumiləşdirmək diaqnostikanı korlayardı.

Etibar reyestri BOŞDURSA heç bir plugin quraşdırılmır (`trust_store_from_env`,
fail-closed). Bu halda istifadəçi ekranda AYDIN səbəb görür — sükutla "heç nə
olmadı" ən pis nəticə olardı, çünki istifadəçi eyni faylı təkrar-təkrar
sınayardı.

──────────────────────────────────────────────────────────────────────────────
MANİFEST PAKETİN İÇİNDƏDİR
──────────────────────────────────────────────────────────────────────────────
İstifadəçidən manifest sahələrini ƏLLƏ soruşmuruq: `capabilities`,
`entry_point` və `publisher` imzanın DAXİLİNDƏDİR (bax `canonical_payload`).
Onları ekranda redaktə etməyə imkan versək, imza ilə manifest arasındakı
bağ qırılar və yoxlama mənasız olardı. Ona görə hər plugin paketi yanında
`<ad>.manifest.json` və `<ad>.sig` faylları gözlənilir.

──────────────────────────────────────────────────────────────────────────────
SİLMƏ SOFT DELETE DEYİL
──────────────────────────────────────────────────────────────────────────────
Kataloqdan (`catalog_admin.py`) fərqli olaraq burada `remove()` fiziki silir —
plugin bir KOD parçasıdır və tarixi qeydə istinad etmir (bax
`PluginManagementUseCase.remove` docstring-i).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginError,
    PluginManifest,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_i import PluginScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Paketin yanında gözlənilən əlavə fayllar (bax modul başlığı).
MANIFEST_SUFFIX = ".manifest.json"
SIGNATURE_SUFFIX = ".sig"


class PluginAdminController:
    """Plugin ekranını `PluginManagementUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: PluginScreen) -> None:
        screen.install_requested.connect(lambda: self._on_install(screen))
        screen.toggle_requested.connect(
            lambda plugin_id, enabled: self._on_toggle(screen, plugin_id, enabled=enabled)
        )
        screen.remove_requested.connect(lambda plugin_id: self._on_remove(screen, plugin_id))
        self.refresh(screen)

    def refresh(self, screen: PluginScreen) -> None:
        """Siyahını bazadan yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                plugins = session.plugins.list_plugins(
                    tenant_id=session.tenant_id, actor=self._actor
                )
        except KompasOSError as error:
            screen.show_error(title="Siyahı açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("PLUGIN_LIST_FAILED")
            screen.show_error(
                title="Siyahı açıla bilmədi",
                message="Plugin siyahısı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        # `as_row()` ekranın FAKTİKİ gözlədiyi açarları verir (`id`, `name`,
        # `version`, `publisher`, `enabled`, `signature`) — maket yolundakı
        # `preview_data.PLUGINS` ilə EYNİ dəst. Burada öz sözlüyümüzü
        # qursaydıq, iki ad məkanı yaranardı (CLAUDE.md bölmə 6).
        screen.set_plugins([plugin.as_row() for plugin in plugins])

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_install(self, screen: PluginScreen) -> None:
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        selected, _filter = QFileDialog.getOpenFileName(
            screen,
            "Plugin paketini seçin",
            "",
            "Plugin faylları (*.py *.zip);;Bütün fayllar (*)",
        )
        if not selected:
            return

        package = Path(selected)
        try:
            manifest, signature_hex = _read_sidecars(package)
        except PluginError as error:
            screen.show_error(title="Paket oxunmadı", message=error.user_message)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.plugins.install(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    plugin_path=package,
                    manifest=manifest,
                    signature_hex=signature_hex,
                )
                session.commit()
        except KompasOSError as error:
            # `PluginSignatureError` də `KompasOSError`-dur: mesajı SƏBƏBİ
            # deyir və olduğu kimi göstərilir (bax modul başlığı).
            screen.show_error(title="Plugin quraşdırılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("PLUGIN_INSTALL_FAILED", extra={"path": str(package)})
            screen.show_error(
                title="Plugin quraşdırılmadı",
                message="Paket qəbul edilmədi. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    def _on_toggle(self, screen: PluginScreen, plugin_id: str, *, enabled: bool) -> None:
        self._write(
            screen,
            lambda session: session.plugins.set_enabled(
                tenant_id=session.tenant_id,
                actor=self._actor,
                plugin_id=plugin_id,
                enabled=enabled,
            ),
            failure_title="Plugin dəyişdirilmədi",
        )

    def _on_remove(self, screen: PluginScreen, plugin_id: str) -> None:
        self._write(
            screen,
            lambda session: session.plugins.remove(
                tenant_id=session.tenant_id, actor=self._actor, plugin_id=plugin_id
            ),
            failure_title="Plugin silinmədi",
        )

    def _write(self, screen: PluginScreen, operation: Any, *, failure_title: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                operation(session)
                session.commit()
        except KompasOSError as error:
            # Rədd edilmiş dəyişiklikdən SONRA siyahı yenidən oxunmalıdır:
            # ekrandakı açar artıq yeni vəziyyəti göstərir və onu belə buraxsaq
            # ekran YALAN danışardı (eyni naxış
            # `root_control.reject_module_change`).
            #
            # LAKİN YENİLƏNMƏ DƏRHAL EDİLMİR (QA-FULL FAZA 3 davamı):
            # `refresh()` → `set_plugins()` → `show_content()` zənciri
            # `ContentSwitcher`-i «content»-ə qaytarır və banner-in ÜSTÜNDƏN
            # yazırdı — hər uğursuz quraşdırma/söndürmə/silmə SÜKUTLA keçirdi,
            # açar isə səbəbsiz geri qayıdırdı. `on_retry` hər iki tələbi
            # ödəyir: səbəb görünür, siyahı isə istifadəçi təsdiqləyəndə
            # bazadakı vəziyyətə qayıdır.
            screen.show_error(
                title=failure_title,
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception("PLUGIN_OPERATION_FAILED")
            screen.show_error(
                title=failure_title,
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
                on_retry=lambda: self.refresh(screen),
            )
            return

        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Paket yanındakı fayllar
# --------------------------------------------------------------------------- #


def _read_sidecars(package: Path) -> tuple[PluginManifest, str]:
    """`<paket>.manifest.json` və `<paket>.sig` fayllarını oxuyur.

    İkisindən biri yoxdursa quraşdırma BAŞLAMIR. Boş imza ilə davam etmək
    `verify()`-ı onsuz da rədd etdirərdi, lakin mesaj "imza uyğun gəlmir"
    olardı — halbuki əsl səbəb faylın ÜMUMİYYƏTLƏ olmamasıdır və istifadəçi
    onu axtarmağı bilməlidir.
    """
    manifest_path = package.with_suffix(package.suffix + MANIFEST_SUFFIX)
    signature_path = package.with_suffix(package.suffix + SIGNATURE_SUFFIX)

    if not manifest_path.exists():
        raise PluginError(
            f"Manifest tapılmadı: {manifest_path.name}",
            user_message=(
                f"Paketin yanında «{manifest_path.name}» faylı olmalıdır — "
                "manifest imzanın tərkib hissəsidir."
            ),
        )
    if not signature_path.exists():
        raise PluginError(
            f"İmza faylı tapılmadı: {signature_path.name}",
            user_message=(
                f"Paketin yanında «{signature_path.name}» faylı olmalıdır — "
                "imzasız paket qəbul edilmir."
            ),
        )

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PluginError(
            f"Manifest oxunmadı: {error}",
            user_message="Manifest faylı düzgün JSON deyil.",
        ) from error

    return (_to_manifest(raw), signature_path.read_text(encoding="utf-8").strip())


def _to_manifest(raw: Any) -> PluginManifest:
    """`manifest.json` → `PluginManifest`.

    Naməlum capability `PluginManifest.__post_init__`-də DEYİL, burada
    tutulur: orada mesaj çoxluq təsviri ilə çıxır (`{...}`), burada isə
    istifadəçiyə hansı dəyərin yanlış olduğu adbaad deyilir.
    """
    if not isinstance(raw, dict):
        raise PluginError(
            "Manifest kök obyekt olmalıdır",
            user_message="Manifest faylının strukturu yanlışdır.",
        )

    capabilities = []
    for value in raw.get("capabilities", []):
        try:
            capabilities.append(PluginCapability(str(value)))
        except ValueError as error:
            raise PluginError(
                f"Naməlum capability: {value}",
                user_message=f"Manifestdə tanınmayan səlahiyyət var: «{value}».",
            ) from error

    return PluginManifest(
        name=str(raw.get("name", "")),
        version=str(raw.get("version", "")),
        publisher=str(raw.get("publisher", "")),
        capabilities=frozenset(capabilities),
        entry_point=str(raw.get("entry_point", "")),
        description_az=str(raw.get("description_az", "")),
        required_flags=frozenset(str(flag) for flag in raw.get("required_flags", [])),
    )


__all__ = ["MANIFEST_SUFFIX", "SIGNATURE_SUFFIX", "PluginAdminController"]
