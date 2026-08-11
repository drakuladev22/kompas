"""ROOT İdarə Mərkəzi kontrolleri — ekran ↔ `RootControlUseCase` (bölmə 3).

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screen_data.py`-DA DEYİL, AYRI FAYLDA
──────────────────────────────────────────────────────────────────────────────
`screen_data.py` YALNIZ oxu yolunu bağlayır: sessiya açır, setter çağırır,
bağlayır. ROOT paneli isə həm oxuyur, HƏM DƏ yazır (limit dəyişikliyi, modul
açarı, yeni flag) və hər yazıdan sonra siyahını yenidən oxumalıdır. Bu dövrə
bir siqnal ömrü boyu yaşamalıdır, `populate()`-ın tək çağırışında yox.

──────────────────────────────────────────────────────────────────────────────
HƏR YAZI ÖZ SESSİYASINDA
──────────────────────────────────────────────────────────────────────────────
Kontroller sessiyanı SAXLAMIR — hər əməliyyat üçün yenisini açır və commit
edir. Səbəb: panel saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu
müddət boyu kilid saxlayardı və `system_limits` cədvəlini bloklayardı.

──────────────────────────────────────────────────────────────────────────────
DƏYİŞMƏYƏN LİMİT YAZILMIR
──────────────────────────────────────────────────────────────────────────────
"Tətbiq Et" bütün sahələri göndərir, lakin yalnız FƏRQLİ olanlar yazılır.
Əks halda hər klik 12 sətirlik "SYSTEM_LIMIT_CHANGED" audit yazısı yaradardı
və audit jurnalı real dəyişiklikləri gizlədərdi (bölmə 3, bənd 4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.application.use_cases.root_control import RootControlError
from src.domain.policies import FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import HardlockLevel, PermissionFlag
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_d import RootControlScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


# --------------------------------------------------------------------------- #
# Ekran mətnləri
# --------------------------------------------------------------------------- #

#: Limit açarı → (etiket, minimum, maksimum, şəkilçi).
#:
#: Diapazon ekranın QSpinBox-u üçündür və məhdudlaşdırıcı DEYİL: bazada
#: kənarda dəyər varsa `limit_row` diapazonu genişləndirir (bax orada).
#: Bu cədvəl tərcümədir, siyasət deyil — həqiqi defolt `DEFAULT_LIMITS`-dədir.
LIMIT_LABELS: dict[SystemLimitKey, tuple[str, int, int, str]] = {
    SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT: ("Aylıq icazə müddəti limiti", 0, 10_000, "dəq"),
    SystemLimitKey.FINE_APPEAL_WINDOW_HOURS: ("Cərimə etiraz pəncərəsi", 1, 8_760, "saat"),
    SystemLimitKey.LATE_TOLERANCE_MINUTES: ("Gecikmə tolerantlığı", 0, 240, "dəq"),
    SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES: (
        "STEP2 / Morning Check-in timeout",
        1,
        1_440,
        "dəq",
    ),
    SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES: ("Cüt nəzarət həddi", 1, 1_440, "dəq"),
    SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS: ("PIN üçün maksimum cəhd", 1, 20, "cəhd"),
    SystemLimitKey.PIN_LOCKOUT_MINUTES: ("PIN bloklama müddəti", 1, 1_440, "dəq"),
    SystemLimitKey.NTP_MAX_DRIFT_SECONDS: ("NTP maksimum sürüşmə", 1, 3_600, "san"),
    SystemLimitKey.MAX_UPLOAD_SIZE_BYTES: ("Maksimum fayl ölçüsü", 1, 104_857_600, "bayt"),
    SystemLimitKey.LEAVE_ALLOWANCE_SOURCE: ("İcazə güzəştinin mənbəyi", 0, 0, ""),
    SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES: ("Sabit güzəşt müddəti", 0, 1_440, "dəq"),
    SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE: ("Gecikmə cərimə dərəcəsi", 0, 0, "AZN/dəq"),
}

#: Modul açarı → Azərbaycanca etiket.
MODULE_LABELS: dict[FeatureModule, str] = {
    FeatureModule.CAMERA_VERIFICATION: "Kamera Təsdiqi (STEP1-3, Morning Check-in)",
    FeatureModule.DUAL_CONTROL: "Cüt-nəzarətli əlavə təsdiq qatı",
    FeatureModule.SHIFT_SWAP: "Növbə dəyişmə sorğuları",
    FeatureModule.FINE_MODULE: "Cərimə modulu",
    FeatureModule.TASK_ENGINE: "Tapşırıq idarəetməsi",
    FeatureModule.SALES_POINTS: "Satış xalları və mükafatlar",
    FeatureModule.DASHBOARD_BUILDER: "Panel qurucusu",
    FeatureModule.SUPPORT_CHAT: "Dəstək çatı",
}


class RootControlController:
    """ROOT panelinin üç bölməsini canlı məlumata bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: RootControlScreen) -> None:
        """Siqnalları bağlayır və ekranı ilk dəfə doldurur."""
        screen.applied.connect(lambda payload: self._on_applied(screen, payload))
        screen.module_toggled.connect(
            lambda key, enabled, confirmation: self._on_module_toggled(
                screen, key, enabled=enabled, confirmation=confirmation
            )
        )
        screen.flag_created.connect(
            lambda code, category, hardlock: self._on_flag_created(
                screen, code, category, hardlock=hardlock
            )
        )
        self.refresh(screen)

    def refresh(self, screen: RootControlScreen) -> None:
        """Üç bölməni bazadan yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                self._fill(session, screen)
        except KompasOSError as error:
            # Səlahiyyət yoxdursa ekran BOŞ deyil, SƏBƏBLƏ göstərilməlidir —
            # boş panel "limit yoxdur" kimi oxunardı.
            screen.show_error(title="Panel açıla bilmədi", message=error.user_message)
        except Exception:
            _error_log.exception("ROOT_CONTROL_LOAD_FAILED")
            screen.show_error(
                title="Panel açıla bilmədi",
                message="Sistem konfiqurasiyası oxuna bilmədi. Yenidən cəhd edin.",
            )

    def _fill(self, session: Session, screen: RootControlScreen) -> None:
        tenant_id = session.tenant_id
        control = session.root_control

        screen.set_limits(
            [
                limit_row(view.key, view.value)
                for view in control.list_limits(tenant_id=tenant_id, actor=self._actor)
            ]
        )
        screen.set_modules(
            [
                (
                    view.module_key,
                    _module_label(view.module_key),
                    view.is_enabled,
                    view.is_structural,
                )
                for view in control.list_modules(tenant_id=tenant_id, actor=self._actor)
            ]
        )
        # Registry `can_manage_permissions` tələb edir; limitlərə icazəsi olan,
        # lakin registry-yə olmayan istifadəçi üçün panel tamamilə bağlanmamalı,
        # yalnız bu bölmə boş qalmalıdır (bölmə 3: yaratma Root-un inhisarında).
        try:
            flags = control.list_flags(actor=self._actor)
        except RootControlError:
            flags = []
        screen.set_registry(
            [(flag.code, flag.hardlock is not HardlockLevel.NONE) for flag in flags]
        )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_applied(self, screen: RootControlScreen, payload: Any) -> None:
        """ "Tətbiq Et" — yalnız DƏYİŞMİŞ limitlər yazılır (bax modul başlığı)."""
        raw = payload.get("limits", {}) if isinstance(payload, dict) else {}
        if not raw:
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                control = session.root_control
                current = {
                    view.key: view.value
                    for view in control.list_limits(tenant_id=session.tenant_id, actor=self._actor)
                }
                changed = 0
                for key_text, value in raw.items():
                    key = _limit_key_or_none(key_text)
                    if key is None:
                        continue
                    new_value = str(value).strip()
                    if not new_value or new_value == current.get(key.value):
                        continue
                    control.set_limit(
                        tenant_id=session.tenant_id,
                        actor=self._actor,
                        key=key,
                        value=new_value,
                    )
                    changed += 1
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Limit yazıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ROOT_CONTROL_LIMIT_FAILED")
            screen.show_error(
                title="Limit yazıla bilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        if changed:
            self.refresh(screen)

    def _on_module_toggled(
        self,
        screen: RootControlScreen,
        module_key: str,
        *,
        enabled: bool,
        confirmation: str,
    ) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.root_control.set_module_enabled(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    module_key=module_key,
                    enabled=enabled,
                    confirmation=confirmation or None,
                )
                session.commit()
        except KompasOSError as error:
            # Ekran YALAN göstərməməlidir: rədd edilibsə açar geri qayıdır.
            screen.reject_module_change(module_key)
            screen.show_error(title="Modul dəyişdirilmədi", message=error.user_message)
        except Exception:
            _error_log.exception("ROOT_CONTROL_TOGGLE_FAILED", extra={"module": module_key})
            screen.reject_module_change(module_key)
            screen.show_error(
                title="Modul dəyişdirilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )

    def _on_flag_created(
        self,
        screen: RootControlScreen,
        code: str,
        category: str,
        *,
        hardlock: bool,
    ) -> None:
        try:
            # "Hardlock" seçimi ƏN DAR səviyyəyə (`ROOT_ONLY`) çevrilir.
            # Səbəb: yeni flag-in nə qədər həssas olduğunu sistem BİLMİR, ona
            # görə ilkin dəyər ən qapalı olmalıdır — genişləndirmək asandır,
            # səhvən verilmiş səlahiyyəti geri almaq isə çətin.
            flag = PermissionFlag(
                code=code,
                category=category,
                hardlock=HardlockLevel.ROOT_ONLY if hardlock else HardlockLevel.NONE,
            )
        except ValueError as error:
            screen.show_error(title="İcazə yaradılmadı", message=str(error))
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.root_control.create_flag(
                    tenant_id=session.tenant_id, actor=self._actor, flag=flag
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="İcazə yaradılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ROOT_CONTROL_FLAG_FAILED", extra={"code": code})
            screen.show_error(
                title="İcazə yaradılmadı",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _limit_key_or_none(value: str) -> SystemLimitKey | None:
    """Naməlum açar SƏSSİZ buraxılır — bazada köhnə sətir qala bilər."""
    try:
        return SystemLimitKey(value)
    except ValueError:
        return None


def _module_label(value: str) -> str:
    """Naməlum modul açarı öz adı ilə göstərilir — gizlədilmir (bax `LimitView`)."""
    try:
        module = FeatureModule(value)
    except ValueError:
        return value
    return MODULE_LABELS.get(module, value)


def limit_row(key_text: str, value: str) -> tuple[str, str, int | str, int, int, str]:
    """Bir limiti ekranın gözlədiyi sətrə çevirir.

    Ədədə çevrilməyən dəyər (məs. "LEAVE_TYPE", "0.00") MƏTN kimi qalır —
    ekran onun üçün sətir sahəsi qurur.
    """
    key = _limit_key_or_none(key_text)
    if key is None:
        # Kodun tanımadığı açar: etiket = açarın özü, sahə mətn.
        return (key_text, key_text, value, 0, 0, "")

    label, minimum, maximum, suffix = LIMIT_LABELS.get(key, (key.value, 0, 1_000_000, ""))
    try:
        number = int(value)
    except (TypeError, ValueError):
        return (key.value, label, value, 0, 0, suffix)

    # Bazadakı dəyər etiket cədvəlindəki diapazondan kənardadırsa, diapazon
    # GENİŞLƏNİR. Əks halda QSpinBox dəyəri sükutla kəsər və Root ekranda
    # bazadakından FƏRQLİ rəqəm görərdi — sonra "Tətbiq Et" onu pozardı.
    low = min(minimum, number)
    high = max(maximum, number)
    return (key.value, label, number, low, high, suffix)


__all__ = ["LIMIT_LABELS", "MODULE_LABELS", "RootControlController", "limit_row"]
