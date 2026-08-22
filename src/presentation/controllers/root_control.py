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

import uuid
from typing import TYPE_CHECKING, Any

from src.application.use_cases.root_control import RootControlError
from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.authorization import HardlockLevel, PermissionFlag
from src.domain.value_objects.face_recognition import FaceToleranceBand, parse_tolerance
from src.domain.value_objects.identifiers import StoreId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.background_task import BackgroundTask, TaskExecutor
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_d import RootControlScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: ROOT panelinin öz flag-i — Face Control mağaza əhatəsi də ona bağlıdır.
#:
#: NİYƏ YENİ FLAG YARADILMADI: mağaza əhatəsi Face Control-un KONFİQURASİYASIDIR
#: (hansı mağazada işləyir), istisna DEYİL (kim üz təsdiqindən azaddır). İkincisi
#: `can_manage_face_exemptions` (hardlock 2) tələb edir və o, ayrı ekrandadır.
#: Konfiqurasiya üçün ROOT panelinin mövcud qapısı düzgün səviyyədir — əks halda
#: hər yeni parametr öz flag-ini gətirər və icazə reyestri şişərdi.
FACE_SCOPE_FLAG = "can_manage_system_limits"

#: Brendinq bölməsi oxunmadıqda göstərilən SAKİT mətn (TENANT-1 Faza 2).
#:
#: Xəta modalı DEYİL: panelin qalan bölmələri (limit, modul, registry) işləyir
#: və istifadəçini «panel açılmadı» ekranına atmaq həmin bölmələri də əlçatmaz
#: edərdi. Registry bölməsi ilə eyni qərar — bax `_fill`.
BRANDING_UNAVAILABLE = (
    "Şirkət kimliyi oxunmadı — bu bölmə müvəqqəti əlçatmazdır. Panelin qalan hissəsi işləyir."
)


# --------------------------------------------------------------------------- #
# Ekran mətnləri
# --------------------------------------------------------------------------- #

#: Limit açarı → (etiket, minimum, maksimum, şəkilçi).
#:
#: Diapazon ekranın QSpinBox-u üçündür və məhdudlaşdırıcı DEYİL: bazada
#: kənarda dəyər varsa `limit_row` diapazonu genişləndirir (bax orada).
#: Bu cədvəl tərcümədir, siyasət deyil — həqiqi defolt `DEFAULT_LIMITS`-dədir.
#:
#: BU CƏDVƏL ARTIQ ETİKETİN ƏSAS MƏNBƏYİ DEYİL (kompas1.md Faza 9). Etiket
#: və diapazon ƏVVƏLCƏ `system_limits` sətrindən (`description_az`,
#: `min_value`, `max_value`) oxunur — bax `limit_row`. Buradakı sətirlər
#: yalnız İKİ boşluğu doldurur: (1) `system_limits`-də ŞƏKİLÇİ sütunu yoxdur,
#: ona görə vahid ("dəq", "saat", "AZN/dəq") yalnız buradan gələ bilər;
#: (2) sətir hələ seed edilməyibsə (yeni açar, köhnə baza) ehtiyat tərcümə.
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
    # --- Faza 10.2 (ikinci dalğa) — təqdimat qatının parametrləri ----------- #
    #
    # ETİKET OLMASA DA GÖRÜNÜRDÜLƏR (`limit_row` naməlum açar üçün adın özünü
    # göstərir) — bu sətirlər yalnız Root-un ekranda TEXNİKİ AD əvəzinə
    # anlaşılan ifadə görməsi üçündür. Diapazonlar migrations/035-dəki
    # `min_value`/`max_value` ilə eynidir.
    SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS: ("Növbə matrisinin pəncərəsi", 1, 120, "gün"),
    SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS: (
        "Sübut yükləmə dövrəsi",
        10,
        3_600,
        "san",
    ),
    SystemLimitKey.ERP_MATCH_LOW_CONFIDENCE_PERCENT: (
        "Zəif uyğunluq həddi (satış)",
        0,
        100,
        "%",
    ),
    SystemLimitKey.DEVELOPER_CRASH_ROW_LIMIT: ("Çökmə cədvəlinin sətir tavanı", 1, 200, "sətir"),
    SystemLimitKey.DEVELOPER_TICKET_ROW_LIMIT: ("Dəstək cədvəlinin sətir tavanı", 1, 200, "sətir"),
    # --- Nahar / Çay fasiləsi (nahar.md) ------------------------------------ #
    #
    # ETİKETLƏR BURADA QISADIR: bu dördü öz bölməsində («Fasilə Parametrləri»)
    # göstərilir və başlıq onsuz da kontekst verir. Baza sətrindəki uzun
    # `description_az` yenə də üstünlük təşkil edir (bax `limit_row`) — bu
    # sətirlər yalnız seed edilməmiş köhnə baza üçün ehtiyatdır. Diapazonlar
    # migrations/045-dəki `min_value`/`max_value` ilə eynidir.
    SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES: ("Nahar fasiləsinin müddəti", 1, 480, "dəq"),
    SystemLimitKey.LUNCH_BREAK_DAILY_COUNT: ("Nahar — gündə neçə dəfə", 0, 10, "dəfə"),
    SystemLimitKey.TEA_BREAK_DURATION_MINUTES: ("Çay fasiləsinin müddəti", 1, 480, "dəq"),
    SystemLimitKey.TEA_BREAK_DAILY_COUNT: ("Çay — gündə neçə dəfə", 0, 10, "dəfə"),
}

#: «Fasilə Parametrləri» bölməsinə yönələn açarlar (nahar.md GUI, bənd 1).
#:
#: SIRA MƏNALIDIR: ekranda «müddət → say» cütü hər fasilə üçün yan-yana
#: durur, çünki Root onları BİRLİKDƏ dəyişir ("nahar 45 dəqiqə, gündə 1").
#: Əlifba sırası ("DAILY_COUNT" → "DURATION") həmin cütü qırardı.
BREAK_LIMIT_KEYS: tuple[SystemLimitKey, ...] = (
    SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES,
    SystemLimitKey.LUNCH_BREAK_DAILY_COUNT,
    SystemLimitKey.TEA_BREAK_DURATION_MINUTES,
    SystemLimitKey.TEA_BREAK_DAILY_COUNT,
)

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

    def __init__(
        self,
        context: ApplicationContext,
        actor: Employee,
        *,
        executor: TaskExecutor | None = None,
    ) -> None:
        """Kontrolleri qurur.

        Args:
            context: Canlı obyekt qrafı.
            actor: Paneli açan istifadəçi.
            executor: Telegram test sorğusunun icraçısı (bax `_on_telegram_
                test`). `None` = Qt sap hovuzu (`erp_servers.py` ilə eyni
                naxış). Testlərdə `InlineExecutor` verilir ki, axın heç bir
                hadisə dövrü gözləməsi olmadan yoxlansın.
        """
        self._context = context
        self._actor = actor
        self._executor = executor
        #: Sonuncu Telegram test buraxılışı — çağırıcı `BackgroundTask.
        #: is_running` ilə ikiqat işə salmanı rədd edir (bax `erp_servers.py`
        #: başlığı: görünən deaktivlik tək başına kifayət etmir, klaviatura
        #: qısayolu düymənin vəziyyətini yan keçə bilər).
        self._telegram_task: BackgroundTask | None = None

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
        # facecontrol.md bənd 15 — mağaza əhatəsi `applied` sözlüyündən AYRI
        # gedir (bax `RootControlScreen.face_scope_changed` şərhi).
        screen.face_scope_changed.connect(
            lambda store_id, active: self._on_face_scope_changed(screen, store_id, active=active)
        )
        # TENANT-1 Faza 2 — brendinq də `applied` sözlüyündən AYRI gedir
        # (bax `RootControlScreen.branding_changed` şərhi).
        screen.branding_changed.connect(lambda payload: self._on_branding_changed(screen, payload))
        # CHAT-1 Faza 3 — Telegram ayarları da `applied` sözlüyündən AYRI
        # gedir (bax `RootControlScreen.telegram_saved` şərhi: token SİRRdir).
        screen.telegram_saved.connect(lambda payload: self._on_telegram_saved(screen, payload))
        screen.telegram_active_changed.connect(
            lambda active: self._on_telegram_active(screen, active=active)
        )
        screen.telegram_test_requested.connect(lambda: self._on_telegram_test(screen))
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

        # HƏR AÇAR YALNIZ BİR BÖLMƏYƏ DÜŞÜR (bax `_build_break_card` başlığı):
        # fasilə açarları ümumi siyahıdan ÇIXARILIR, qalanı olduğu kimi qalır.
        # Bu, `test_root_control_lists_every_key_without_a_curated_allowlist`-in
        # qadağan etdiyi «əl ilə seçilmiş siyahı» DEYİL — use case yenə də
        # BÜTÜN açarları qaytarır; burada yalnız hansı KARTA düşdüyü həll
        # olunur və yeni açar defolt olaraq ümumi siyahıda görünür.
        break_keys = {key.value for key in BREAK_LIMIT_KEYS}
        rows = [
            (
                view.key,
                limit_row(
                    view.key,
                    view.value,
                    description_az=view.description_az,
                    min_value=view.min_value,
                    max_value=view.max_value,
                    is_stored=view.is_stored,
                ),
            )
            for view in control.list_limits(tenant_id=tenant_id, actor=self._actor)
        ]
        screen.set_limits([row for key, row in rows if key not in break_keys])
        # Ekranda göstərilmə sırası `BREAK_LIMIT_KEYS`-dən gəlir, bazanın
        # qaytardığı sıradan yox — «müddət → say» cütü pozulmasın deyə.
        by_key = dict(rows)
        screen.set_break_limits(
            [by_key[key.value] for key in BREAK_LIMIT_KEYS if key.value in by_key]
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

        # facecontrol.md bənd 15 + (7, 12). Hər ikisi `set_limits`-dən SONRA
        # gəlir, çünki `set_limits` `show_content()` çağırır — əks sırada
        # kartlar doldurulub, sonra ekran vəziyyəti dəyişərdi.
        screen.set_face_scope(face_scope_rows(session))
        screen.set_face_tolerance(face_tolerance_row(session))

        # TENANT-1 Faza 2. Oxunuş İCAZƏ TƏLƏB ETMİR (bax `tenant_branding.py`
        # başlığı) — lakin bu panelə onsuz da yalnız Root çıxır. Xəbərdarlıq
        # BURADA da hesablanır: uyğunsuz rəng əvvəlki sessiyada yazılmış ola
        # bilər və panel onu yenidən açanda yenə görünməlidir.
        #
        # BÖLMƏ AYRICA DÜŞÜR, PANELİ BAĞLAMIR — registry bölməsi ilə eyni
        # qərar (yuxarıda). `tenant_branding` cədvəli YENİDİR (migrations/064):
        # miqrasiya hələ tətbiq olunmamış quraşdırmada sorğu xəta verər və o
        # halda Root paneli TAMAMİLƏ açılmazdı — yəni bir görünüş ayarı
        # ucbatından limit/toggle idarəsi əlçatmaz olardı.
        try:
            branding = session.branding.current(tenant_id)
        except Exception:
            _error_log.exception("ROOT_BRANDING_SECTION_UNAVAILABLE")
            screen.set_branding(company_name="", accent_color="")
            screen.set_branding_status(BRANDING_UNAVAILABLE)
            return
        screen.set_branding(
            company_name=branding.company_name,
            accent_color=branding.accent_color or "",
            warning=branding.accessibility_warning(),
        )
        screen.set_branding_status("")

        # TELEGRAM KARTI SONDA: brendinq bölməsi ilə eyni qərar — bir kartın
        # oxunmaması qalan bölmələri görünməz etməməlidir.
        try:
            self._fill_telegram(session, screen)
        except Exception:
            _error_log.exception("ROOT_TELEGRAM_SECTION_UNAVAILABLE")
            screen.set_telegram_message(
                "Telegram ayarları oxunmadı — digər bölmələr işləyir.", error=True
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
        """Modul aç/söndür — RƏDD BÜTÜN PANELİ ƏVƏZ ETMİR (QA-FULL FAZA 3).

        ──────────────────────────────────────────────────────────────────────
        ƏVVƏL `show_error()` İDİ — TAPINTI
        ──────────────────────────────────────────────────────────────────────
        `show_error()` `ContentSwitcher`-i xəta vəziyyətinə keçirir və bir
        modulun rəddi (məs. qısa təsdiq mətni) limitləri, fasilə
        parametrlərini, Face Control-u, brendinqi və registri də GİZLƏDİRDİ,
        halbuki `reject_module_change()` artıq YALNIZ həmin açarı geri
        qaytarıb — qalan ekran sağlamdır. `screen.set_module_message(...)`
        `set_telegram_message` ilə EYNİ naxışdır: mətn Modul kartının İÇİNDƏ
        qalır, `ContentSwitcher` toxunulmur — istifadəçi HƏM domendən gələn
        dəqiq səbəbi görür, HƏM DƏ panelin qalan hissəsini itirmir.
        """
        # Köhnə rədd mətni HƏR CƏHDDƏ təmizlənir: əks halda əvvəlki
        # xəbərdarlıq yeni cəhdin (uğurlu ola biləcək) nəticəsini maskalayardı.
        screen.set_module_message("")
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
            screen.set_module_message(error.user_message, error=True)
        except Exception:
            _error_log.exception("ROOT_CONTROL_TOGGLE_FAILED", extra={"module": module_key})
            screen.reject_module_change(module_key)
            screen.set_module_message("Dəyişiklik saxlanmadı. Yenidən cəhd edin.", error=True)

    def _on_branding_changed(self, screen: RootControlScreen, payload: object) -> None:
        """Şirkət kimliyi (TENANT-1 Faza 2) — use case YAZIR, kontroller körpüdür.

        `face_scope` naxışından FƏRQİ: orada hazır use case yox idi və
        kontroller səlahiyyəti özü yoxlayırdı. Burada `TenantBrandingUseCase`
        VAR və qapı ONUN içindədir (`_require`) — kontrollerin ikinci yoxlama
        yazması qaydanı iki yerə bölərdi və biri dəyişəndə digəri köhnələrdi.

        Uyğun olmayan rəng RƏDD EDİLMİR: use case onu saxlayır və xəbərdarlıq
        qaytarır; ekran həmin mətni göstərir (bax `value_objects/branding.py`).
        """
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                result = session.branding.update(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    company_name=str(payload.get("company_name", "")),
                    accent_color=_optional_text(payload.get("accent_color")),
                    clear_accent=bool(payload.get("clear_accent")),
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Şirkət kimliyi yazılmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("TENANT_BRANDING_WRITE_FAILED")
            screen.show_error(
                title="Şirkət kimliyi yazılmadı",
                message="Dəyər saxlanmadı. Yenidən cəhd edin.",
            )
            return

        screen.set_branding(
            company_name=result.branding.company_name,
            accent_color=result.branding.accent_color or "",
            warning=result.warning,
        )
        # Başlıq zolağı DƏRHAL yenilənmir və bu, qəsdəndir: ad pəncərənin
        # ömrü boyu bir dəfə tətbiq olunur (`app._apply_tenant_branding`) və
        # onu iş vaxtı dəyişdirmək açıq ekranların başlığı ilə pəncərə adını
        # bir-birindən ayıra bilərdi. Dəyişiklik növbəti açılışda görünür.
        screen.set_branding_status(
            "Şirkət kimliyi yadda saxlanıldı. Başlıq zolağı proqramın növbəti "
            "açılışında yenilənəcək."
        )

    def _fill_telegram(self, session: Session, screen: RootControlScreen) -> None:
        """Telegram bölməsini doldurur — SƏLAHİYYƏTSİZ İSTİFADƏÇİDƏ BOŞ QALIR.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ ÖZ İSTİSNASINI UDUR
        ──────────────────────────────────────────────────────────────────────
        Bu, ROOT panelinin BİR kartıdır. İstisna yuxarı qalxsaydı, `refresh`
        onu tutar və bütün panel «açıla bilmədi» xəbəri ilə BOŞ qalardı —
        yəni Telegram konfiqurasiyasının oxunmaması limitləri, modul
        açarlarını və icazə registrini də görünməz edərdi.

        `may_manage` isə istisnadan ƏVVƏL yoxlanılır: `current()` Root
        olmayan aktora istisna atır və hər açılışda jurnal doldurardı.
        Faktiki qapı yenə də use case-dədir (yazı yolu `_require`-dan keçir);
        buradakı yoxlama YALNIZ göstərmə qərarıdır.
        """
        if not session.telegram_config.may_manage(self._actor):
            return
        view = session.telegram_config.current(tenant_id=session.tenant_id, actor=self._actor)
        screen.set_telegram(
            {
                "masked_token": view.masked_token,
                "chat_id": view.chat_id,
                "is_active": view.is_active,
                "updated_at": (
                    view.updated_at.strftime("%d.%m.%Y %H:%M")
                    if view.updated_at is not None
                    else ""
                ),
                "updated_by_name": view.updated_by_name,
            }
        )

    def _on_telegram_saved(self, screen: RootControlScreen, payload: object) -> None:
        """«Botu Dəyiş» — köhnə sətir ARXİVLƏNİR, yenisi yazılır."""
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                view = session.telegram_config.save(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    bot_token=str(payload.get("bot_token", "")),
                    chat_id=str(payload.get("chat_id", "")),
                )
                session.commit()
        except KompasOSError as error:
            screen.set_telegram_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("TELEGRAM_CONFIG_WRITE_FAILED")
            screen.set_telegram_message(
                "Telegram ayarları saxlanmadı. Yenidən cəhd edin.", error=True
            )
            return
        screen.set_telegram(
            {
                "masked_token": view.masked_token,
                "chat_id": view.chat_id,
                "is_active": view.is_active,
                "updated_at": (
                    view.updated_at.strftime("%d.%m.%Y %H:%M")
                    if view.updated_at is not None
                    else ""
                ),
                "updated_by_name": view.updated_by_name,
            }
        )
        screen.set_telegram_message(
            "Bot yeniləndi. Köhnə token arxivləndi — «Test Mesajı Göndər» ilə yoxlayın."
        )

    def _on_telegram_active(self, screen: RootControlScreen, *, active: bool) -> None:
        """Aktiv/Deaktiv — token TOXUNULMUR (bax use case başlığı)."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.telegram_config.set_active(
                    tenant_id=session.tenant_id, actor=self._actor, is_active=active
                )
                session.commit()
        except KompasOSError as error:
            screen.set_telegram_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("TELEGRAM_CONFIG_ACTIVATION_FAILED")
            screen.set_telegram_message("Vəziyyət dəyişmədi. Yenidən cəhd edin.", error=True)
            return
        screen.set_telegram_message(
            "Telegram bildirişləri aktivdir."
            if active
            else "Telegram bildirişləri dayandırıldı — mesajlar proqramda qalır."
        )

    def _on_telegram_test(self, screen: RootControlScreen) -> None:
        """`[Test Mesajı Göndər]` — sorğu FON SAPINDA icra olunur (UI-4).

        ──────────────────────────────────────────────────────────────────────
        ƏVVƏL SİNXRON İDİ — DÖVRƏ 4 AUDİTİNİN TAPINTISI
        ──────────────────────────────────────────────────────────────────────
        Bu çağırış birbaşa `httpx` ilə Telegram-a POST göndərir
        (`infrastructure/notifications/telegram.py`) və taymaut
        `SystemLimitKey.TELEGRAM_REQUEST_TIMEOUT_SECONDS`-dir (defolt 15 san,
        Root 120 san-a qədər böyüdə bilər). Sinxron çağırıldıqda bütün ROOT
        paneli həmin müddət ərzində HEÇ BİR göstərici olmadan donurdu — eyni
        kateqoriya `erp_servers.py`-dəki ERP bağlantı testi ilə (bax onun
        başlığı) və düzəliş də EYNİ naxışla (`background_task.run_job`) həll
        olunur.

        «Göndərilmədi» cavabı da nəticədir: səbəbi jurnalda, faktı isə
        ekranda olmalıdır, əks halda Root düyməni basıb heç nə görməzdi.
        """
        from src.presentation.background_task import run_job  # noqa: PLC0415

        if self._telegram_task is not None and self._telegram_task.is_running:
            return

        screen.set_telegram_busy(True)
        self._telegram_task = run_job(
            self._send_telegram_test,
            on_success=lambda delivered: self._on_telegram_test_succeeded(screen, delivered),
            on_failure=lambda error: self._on_telegram_test_failed(screen, error),
            owner=screen,
            name="TELEGRAM_TEST",
            executor=self._executor,
        )

    def _send_telegram_test(self) -> bool:
        """FON SAPINDA icra olunur — ÖZ sessiyasını açır (bax `erp_servers.py`).

        Əsas sapda qurulmuş sessiya ötürülmür: `psycopg` bağlantısı sap-
        təhlükəsiz deyil.
        """
        with self._context.session(user_id=self._actor.id) as session:
            delivered = session.telegram_config.send_test_message(
                tenant_id=session.tenant_id, actor=self._actor
            )
            session.commit()
            return delivered

    def _on_telegram_test_succeeded(self, screen: RootControlScreen, delivered: object) -> None:
        """Nəticə ƏSAS SAPDA qəbul edilir — burada Qt widget-ə TOXUNULA bilər."""
        screen.set_telegram_busy(False)
        if delivered:
            screen.set_telegram_message("Test mesajı göndərildi — Telegram qrupunu yoxlayın.")
        else:
            screen.set_telegram_message(
                "Test mesajı çatmadı. Token, chat ID və internet bağlantısını yoxlayın.",
                error=True,
            )

    def _on_telegram_test_failed(self, screen: RootControlScreen, error: BaseException) -> None:
        """Fon işində qalan istisna — SÜKUTLA UDULMUR (bax `erp_servers.py::_show_test_error`)."""
        screen.set_telegram_busy(False)
        if isinstance(error, KompasOSError):
            screen.set_telegram_message(error.user_message, error=True)
            return
        _error_log.error("TELEGRAM_TEST_FAILED", exc_info=error)
        screen.set_telegram_message("Test mesajı göndərilmədi.", error=True)

    def _on_face_scope_changed(
        self, screen: RootControlScreen, store_id: str, *, active: bool
    ) -> None:
        """Face Control mağaza əhatəsi (bənd 15) — SOFT DELETE ilə yazılır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ USE CASE YOX, REPOSITORY + AUDİT
        ──────────────────────────────────────────────────────────────────────
        `face_control_store_scope` `system_limits` sətri DEYİL, ona görə
        `RootControlUseCase.set_limit` yolu ona uyğun gəlmir; `FaceControl
        ExemptionUseCase` isə tamamilə başqa flag-in (hardlock 2) arxasındadır.
        Layihədə bu vəziyyət üçün hazır naxış var və o, `controllers/
        drive_connection.py`-dədir: kontroller səlahiyyəti AÇIQ yoxlayır,
        repository-yə yazır və audit sətrini ÖZÜ yazır.

        AUDİT SƏTRİ MƏCBURİDİR: mağazanın əhatəyə salınması/çıxarılması
        həmin mağazadakı BÜTÜN girişlərin üz təsdiqindən keçib-keçmədiyini
        müəyyən edir. Onsuz «bu ay niyə heç bir uyğunsuzluq qeydə alınmayıb?»
        sualının cavabı yoxa çıxardı.

        SƏTİR SİLİNMİR (`set_active(active=False)`): sxem `chk_face_scope_
        deactivation` ilə çıxarılmış sətrin `deactivated_at`-ını MƏCBUR edir.

        ──────────────────────────────────────────────────────────────────────
        QLOBAL → DAR ƏHATƏ KEÇİDİ AYRICA SƏNƏDLƏŞDİRİLİR (DEEP-GAP FAZA 4, T4)
        ──────────────────────────────────────────────────────────────────────
        `FaceStoreScope.is_global` boş dəst = qlobal davranış deyir (bax onun
        şərhi). Yəni `active=True` ilə ƏLAVƏ OLUNAN İLK mağaza — hazırkı əhatə
        `is_global`-dırsa — audit mətnindəki "aktivləşdirildi" sözü YALANDIR:
        faktiki nəticə budur ki, BÜTÜN DİGƏR mağazalarda üz təsdiqi SÜKUTLA
        SÖNÜR (yalnız seçilən mağaza qalır). Bu, əvvəl `after_state`-də HEÇ
        GÖRÜNMÜRDÜ. İndi keçiddən ƏVVƏL cari əhatə oxunur və `is_global`-dırsa
        digər bütün AKTİV mağazaların ID-ləri `implicitly_disabled_store_ids`
        açarı ilə eyni audit sətrinə yazılır — "aktivləşdirildi" yox, "əhatə
        DARALDI, qalanlar sükutla söndürüldü" mənasında.
        """
        if not self._permitted():
            _security_log.warning(
                "FACE_SCOPE_DENIED",
                extra={"actor_id": str(self._actor.id), "flag": FACE_SCOPE_FLAG},
            )
            screen.reject_face_scope_change(store_id)
            screen.show_error(
                title="Əhatə dəyişdirilmədi",
                message="Face Control mağaza əhatəsini yalnız ROOT dəyişə bilər.",
            )
            return

        target = _store_id_or_none(store_id)
        if target is None:
            screen.reject_face_scope_change(store_id)
            screen.show_error(
                title="Əhatə dəyişdirilmədi", message="Mağaza identifikatoru düzgün deyil."
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                scope_repo = session.uow.repository("face_store_scope")
                narrowed_from: list[str] = []
                if active and scope_repo.active_scope(session.tenant_id).is_global:
                    # QLOBAL İDİ, bu mağaza ONU DARALDIR — digər bütün AKTİV
                    # mağazalar bu andan üz təsdiqindən KƏNARDA qalır.
                    rows = session.uow.connection.execute(
                        "SELECT id FROM stores WHERE tenant_id = %s AND is_active AND id <> %s",
                        (session.tenant_id, target),
                    ).fetchall()
                    narrowed_from = [str(row["id"]) for row in rows]

                scope_repo.set_active(
                    session.tenant_id,
                    target,
                    active=active,
                    changed_by=self._actor.id,
                )
                after_state: dict[str, Any] = {"store_id": str(target), "is_active": active}
                reason = "Face Control mağaza əhatəsi dəyişdirildi (facecontrol.md bənd 15)"
                if narrowed_from:
                    after_state["implicitly_disabled_store_ids"] = narrowed_from
                    reason = (
                        "Face Control əhatəsi qlobaldan DAR əhatəyə keçdi — "
                        f"{len(narrowed_from)} digər mağazada üz təsdiqi sükutla "
                        "söndürüldü (facecontrol.md bənd 15)"
                    )
                session.uow.audit.record(
                    tenant_id=session.tenant_id,
                    actor_id=self._actor.id,
                    action="FACE_SCOPE_CHANGED",
                    entity_type="face_control_store_scope",
                    entity_id=target,
                    after_state=after_state,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.reject_face_scope_change(store_id)
            screen.show_error(title="Əhatə dəyişdirilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("FACE_SCOPE_WRITE_FAILED", extra={"store_id": store_id})
            screen.reject_face_scope_change(store_id)
            screen.show_error(
                title="Əhatə dəyişdirilmədi",
                message="Dəyişiklik saxlanmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    def _permitted(self) -> bool:
        """`can_manage_system_limits` — `drive_connection._permitted` naxışı.

        VAXT `self._context.clock`-DAN GƏLİR, `datetime.now(UTC)`-DAN YOX
        (DEEP-GAP FAZA 4, T5): bu, yeganə qapıdır — use case yoxdur,
        kontroller birbaşa repository-yə yazır. `datetime.now(UTC)` OS
        saatındandır, halbuki TIME-1 (`migrations/062`) portun SERVER-
        lövbərli olmasını vəd edir. OS saatı geri çəkilsə, artıq müddəti
        bitmiş fərdi override yenidən "aktiv" görünə bilərdi
        (`PermissionOverride.is_active`-in `expires_at > now` şərti).
        """
        return bool(self._actor.has_permission(FACE_SCOPE_FLAG, now=self._context.clock.now()))

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


def _bound_or(raw: str | None, fallback: int) -> int:
    """`system_limits.min_value`/`max_value` → tam ədəd, alınmasa ehtiyat.

    Sütun TEXT-dir və DECIMAL limitlərdə "0.1" kimi dəyər saxlayır. Belə
    limit onsuz da QSpinBox-a düşmür (dəyərin özü ədəd deyil, sahə mətndir),
    ona görə burada `int()` uğursuzluğu XƏTA DEYİL — sadəcə "bu hədd
    spin-qutu üçün deyil" deməkdir və ehtiyat diapazon qalır.
    """
    if raw is None:
        return fallback
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback


def limit_row(
    key_text: str,
    value: str,
    *,
    description_az: str = "",
    min_value: str | None = None,
    max_value: str | None = None,
    is_stored: bool = True,
) -> tuple[str, str, int | str, int, int, str]:
    """Bir limiti ekranın gözlədiyi sətrə çevirir.

    Ədədə çevrilməyən dəyər (məs. "LEAVE_TYPE", "0.00") MƏTN kimi qalır —
    ekran onun üçün sətir sahəsi qurur.

    ──────────────────────────────────────────────────────────────────────────
    ETİKET NİYƏ ƏVVƏLCƏ BAZADAN OXUNUR
    ──────────────────────────────────────────────────────────────────────────
    `system_limits` sətri onsuz da `description_az`, `min_value`, `max_value`
    daşıyır (schema.sql §-də sütunlar, hər miqrasiyada seed edilir) və
    `LimitView` onları ekrana qədər gətirir. Əvvəllər bu funksiya yalnız
    `(key, value)` alırdı, yəni həmin üç sütun SÜKUTLA atılırdı və etiket
    `LIMIT_LABELS`-dən — ƏL İLƏ yazılmış 17 sətirlik cədvəldən — gəlirdi.
    Nəticə: 166 açarın 149-u ROOT ekranında `EXPORT_STORE_ANOMALY_MIN_EMPLOYEES`
    kimi TEXNİKİ KOD görünürdü (bölmə 4: interfeys dili Azərbaycancadır) və
    hamısı eyni 0–1 000 000 diapazonu ilə açılırdı — yəni faizlik parametrə
    500 000 yazmaq mümkün idi.

    Bu, `test_root_control_lists_every_key_without_a_curated_allowlist`-in
    açar SİYAHISI üçün qadağan etdiyi naxışın etiket variantıdır: əl ilə
    saxlanan cədvəl yeni parametrləri sükutla arxada qoyur. Ona görə mənbə
    sırası indi belədir — baza sətri → `LIMIT_LABELS` → açarın öz kodu.

    ŞƏKİLÇİ İSTİSNADIR: `system_limits`-də vahid sütunu YOXDUR, ona görə
    "dəq"/"saat"/"AZN/dəq" yalnız `LIMIT_LABELS`-dən gələ bilər. Vahid üçün
    sütun əlavə etmək bütün seed sətirlərini yenidən yazmaq demək olardı,
    halbuki vahid tərcümə məsələsidir — siyasət deyil.

    Args:
        key_text: `system_limits.limit_key`.
        value: Cari dəyər (mətn kimi — tip bazada `value_type`-dadır).
        description_az: Baza sətrinin Azərbaycanca izahı; boşdursa ehtiyat
            mənbələr işə düşür.
        min_value: Baza sətrinin aşağı həddi (mətn); ədədə çevrilməzsə
            nəzərə alınmır.
        max_value: Baza sətrinin yuxarı həddi (mətn); eyni qayda.
        is_stored: Sətir `system_limits`-də varmı. `False` olanda etiketə
            xəbərdarlıq şəkilçisi qoşulur — Root dəyəri dəyişməmişdən əvvəl
            onun hələ defolt olduğunu görməlidir.
    """
    key = _limit_key_or_none(key_text)
    if key is None:
        # Kodun tanımadığı açar: etiket = baza izahı, yoxdursa açarın özü.
        # Sahə mətndir, çünki kod onun tipini bilmir.
        return (key_text, description_az.strip() or key_text, value, 0, 0, "")

    fallback_label, minimum, maximum, suffix = LIMIT_LABELS.get(key, (key.value, 0, 1_000_000, ""))
    label = description_az.strip() or fallback_label
    if not is_stored:
        label = f"{label} — defolt (bazada yazılmayıb)"
    minimum = _bound_or(min_value, minimum)
    maximum = _bound_or(max_value, maximum)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return (key.value, label, value, 0, 0, suffix)

    # Bazadakı dəyər diapazondan kənardadırsa, diapazon GENİŞLƏNİR. Əks halda
    # QSpinBox dəyəri sükutla kəsər və Root ekranda bazadakından FƏRQLİ rəqəm
    # görərdi — sonra "Tətbiq Et" onu pozardı.
    #
    # `min`/`max` cütü tərs seed sətrini də zərərsizləşdirir (`min_value` >
    # `max_value`): QSpinBox belə diapazonda hər iki həddi aşağı dəyərə
    # sıxışdırar və sahə redaktə edilə bilməz olardı.
    low = min(minimum, maximum, number)
    high = max(minimum, maximum, number)
    return (key.value, label, number, low, high, suffix)


def _optional_text(value: object) -> str | None:
    """Siqnal sözlüyündən gələn dəyəri `str | None`-a gətirir.

    Qt siqnalı `dict[str, object]` daşıyır və tip zəmanəti orada itir. Dəyəri
    `str()`-ə basmaq `None`-u «None» sətrinə çevirərdi — use case isə `None`-u
    «dəyişmə» kimi oxuyur, yəni fərq DAVRANIŞ fərqidir.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _store_id_or_none(value: str) -> StoreId | None:
    """Naməlum/yararsız identifikator yazı yoluna GETMİR."""
    try:
        return StoreId(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError):
        return None


def face_scope_rows(session: Session) -> list[dict[str, str]]:
    """Face Control mağaza əhatəsi — ekranın gözlədiyi açarlar (bənd 15).

    AKTİV MAĞAZALAR CƏDVƏLDƏN, SEÇİM İSƏ ƏHATƏ SƏTİRLƏRİNDƏN gəlir. İkisi
    ayrı mənbədir və qəsdən belədir: əhatədən çıxarılmış sətir SİLİNMİR
    (soft delete), yəni əhatə cədvəlini tək başına oxumaq «bir vaxt seçilmiş,
    sonra çıxarılmış» mağazanı da seçilmiş göstərərdi.
    """
    scope = session.uow.repository("face_store_scope").active_scope(session.tenant_id)
    rows = session.uow.connection.execute(
        """
        SELECT id, name FROM stores
         WHERE tenant_id = %s AND is_active
         ORDER BY name
        """,
        (session.tenant_id,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "active": "1" if scope.covers(StoreId(row["id"])) and not scope.is_global else "0",
        }
        for row in rows
    ]


def face_tolerance_row(session: Session) -> dict[str, str]:
    """İki ROOT həddi + TƏRS CÜT bayrağı (bənd 7 + 12).

    ──────────────────────────────────────────────────────────────────────────
    QƏRAR BURADA VERİLMİR — `FaceToleranceBand.resolve` VERİR
    ──────────────────────────────────────────────────────────────────────────
    Şərti («aşağı-etibar həddi bənzərlik həddindən böyükdürsə...») burada
    yenidən yazmaq domen qaydasının İKİNCİ NÜSXƏSİ olardı və iki nüsxə bir
    müddət üst-üstə düşüb sonra sükutla ayrılardı — `menu.py` başlığındakı
    qüsurun eynisi. Ona görə eyni funksiya çağırılır və nəticənin YALNIZ
    bayraqları ekrana ötürülür.

    XAM DƏYƏRLƏR GÖSTƏRİLİR, HESABLANMIŞ DEYİL: Root ekranda ÖZ yazdığı
    ədədləri görməlidir. Sistemin FAKTİKİ tətbiq etdiyi hədd tərs cütdə
    fərqlidir və məhz bu fərq xəbərdarlığın mövzusudur (bax `set_face_
    tolerance`).
    """
    match_raw = _limit_str(session, SystemLimitKey.FACE_MATCH_TOLERANCE)
    low_raw = _limit_str(session, SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE)
    band = FaceToleranceBand.resolve(
        match_tolerance=parse_tolerance(
            match_raw, fallback=float(DEFAULT_LIMITS[SystemLimitKey.FACE_MATCH_TOLERANCE])
        ),
        low_confidence_tolerance=parse_tolerance(
            low_raw,
            fallback=float(DEFAULT_LIMITS[SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE]),
        ),
    )
    return {
        "match": match_raw,
        "low_confidence": low_raw,
        "inverted": "1" if band.is_inverted else "0",
        "band_enabled": "1" if band.band_enabled else "0",
    }


def _limit_str(session: Session, key: SystemLimitKey) -> str:
    value: str = session.limits.get_str(session.tenant_id, key.value, DEFAULT_LIMITS[key])
    return value


__all__ = [
    "BREAK_LIMIT_KEYS",
    "FACE_SCOPE_FLAG",
    "LIMIT_LABELS",
    "MODULE_LABELS",
    "RootControlController",
    "face_scope_rows",
    "face_tolerance_row",
    "limit_row",
]
