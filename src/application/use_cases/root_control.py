"""ROOT İdarə Mərkəzi — tenant-səviyyəli idarəetmə (5-ci faza, bənd 5).

──────────────────────────────────────────────────────────────────────────────
BU PANEL SAAS DEVELOPER PANELİ DEYİL
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya bunu açıq şəkildə ayırır: bura tenant-ın ÖZ `Root`
istifadəçisinin panelidir, Faza 6-dakı Master Lisenziya Panelindən TAM
AYRIDIR. Burada tenant öz limitlərini, modullarını və icazə kataloqunu idarə
edir; başqa tenant-ın məlumatına çıxış YOXDUR — hər metod `tenant_id` alır və
onu sorğuya ötürür.

──────────────────────────────────────────────────────────────────────────────
ÜÇ EKRAN, ÜÇ FƏRQLİ RİSK SƏVİYYƏSİ
──────────────────────────────────────────────────────────────────────────────
    1. **Sistem Limitləri** (`can_manage_system_limits`) — geri qaytarıla bilən
       ədədi konfiqurasiya. Səhv dəyər növbəti dəyişikliklə düzəlir.
    2. **Feature Toggles** (`can_manage_system_limits`) — modul söndürmək iş
       axınını dayandırır. Struktur-kritik modul üçün YAZILI TƏSDİQ tələb
       olunur və qayda repository qatındadır (modal-ı yan keçən skript də
       ona tabedir).
    3. **Permission Registry** (`can_manage_permissions`, YALNIZ Root) — yeni
       flag yaratmaq icazə modelini genişləndirir. Geri qaytarılması ən çətin
       olan əməliyyatdır, ona görə ən dar səlahiyyətlə qorunur.

──────────────────────────────────────────────────────────────────────────────
RETROAKTİV-TƏSİRSİZLİK QAYDASI
──────────────────────────────────────────────────────────────────────────────
Bölmə 3: modul söndürüldükdə MÖVCUD instansiyalar öz axınını normal tamamlayır
— yalnız YENİ instansiya yaradılması bloklanır. Bu qayda burada TƏTBİQ
OLUNMUR, çünki o, hər modulun öz use case-inin girişindədir (`is_enabled`
yoxlaması). Burada onu təkrarlamaq "söndürüldü, deməli hamısını dayandır"
kimi yanlış davranışa gətirərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.policies import (
    AVAILABLE_UI_LANGUAGES,
    DEFAULT_LIMITS,
    FACE_EXEMPTION_COMPENSATING_MODULE,
    FeatureModule,
    SystemLimitKey,
)
from src.domain.value_objects.authorization import SystemRole
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        FaceExemptionRepository,
        FeatureToggles,
        PermissionFlagRepository,
        SystemLimits,
    )
    from src.domain.value_objects.authorization import PermissionFlag
    from src.domain.value_objects.identifiers import TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

MANAGE_LIMITS_FLAG = "can_manage_system_limits"
MANAGE_PERMISSIONS_FLAG = "can_manage_permissions"

#: Struktur-kritik modulu söndürmək üçün minimum təsdiq mətni uzunluğu.
#: "ok" yazmaq təsdiq deyil — istifadəçi nə etdiyini ifadə etməlidir.
#:
#: ──────────────────────────────────────────────────────────────────────────
#: BU ƏDƏD QƏSDƏN `system_limits`-Ə KÖÇÜRÜLMÜR (Faza 10.2 qərarı)
#: ──────────────────────────────────────────────────────────────────────────
#: CLAUDE.md §5 hər sabit üçün "bu, struktur zəmanətdirmi?" sualını tələb edir.
#: Cavab burada BƏLİ-dir və səbəb ədədin özündə deyil, ONU KİMİN DƏYİŞDİYİNDƏ:
#:
#:   * Həm `set_limit`, həm də `set_module_enabled` EYNİ flag-i tələb edir
#:     (`can_manage_system_limits`). Yəni bu həddi `system_limits`-ə köçürsək,
#:     modulu söndürmək istəyən aktor ƏVVƏLCƏ öz qarşısındakı maneəni `1`-ə
#:     endirə, sonra "x" yazıb `CAMERA_VERIFICATION`-ı bağlaya bilərdi. Qoruma
#:     ilə qorunan şeyi eyni adam idarə edəndə qoruma qalmır — bu, Self-
#:     Escalation Guard-ın qadağan etdiyi naxışın forması ilə eynidir.
#:   * Qayda İKİ YERDƏDİR (CLAUDE.md §5): burada UZUNLUQ, repository-də isə
#:     MÖVCUDLUQ yoxlanılır, çünki ekranı yan keçən skript də ona tabe
#:     olmalıdır. Root-dan dəyişdirilə bilən yarım qayda həmin ikili qapının
#:     bir qanadını sükutla açardı.
#:   * Bu, `MIN_REASON_LENGTH` / `MIN_SUBJECT_LENGTH` ilə eyni ailədəndir:
#:     mətn-uzunluğu validatorları məzmun keyfiyyəti qaydasıdır, əməliyyat
#:     limiti deyil — onların heç biri ROOT parametrinə çevrilmir.
#:
#: Dəyişdirmək lazım gələrsə, bu kod buraxılışı ilə edilir və qərar
#: `docs/security_decisions.md`-də qeyd olunur.
MIN_CONFIRMATION_LENGTH = 6


class RootControlError(KompasOSError):
    """ROOT əməliyyatı qadağandır və ya yararsızdır."""

    user_message = "Bu əməliyyat icra edilə bilmədi."


class StructuralModuleError(RootControlError):
    """Struktur-kritik modul təsdiqsiz söndürülməyə çalışıldı."""

    user_message = (
        "Bu modul sistemin struktur hissəsidir. Söndürmək üçün təsdiq mətni yazmalısınız."
    )


class CompensatingControlLockedError(RootControlError):
    """Modul BAŞQA bir struktur zəmanətin kompensasiyasını daşıyır (SEC-020).

    `StructuralModuleError`-dan FƏRQLİDİR VƏ AYRI SİNİF OLMASI QƏSDƏNDİR:
    orada cavab «təsdiq mətni yaz» (yəni əməliyyat mümkündür, sənədləşdirilməli
    olur), burada isə əməliyyat QƏTİ ŞƏKİLDƏ mümkün deyil — əvvəlcə asılı olan
    zəmanət aradan qaldırılmalıdır. Eyni sinifdən istifadə etsəydik, ekran
    istifadəçiyə "təsdiq yazın" deyər, təsdiq yazılandan sonra isə yenidən
    rədd edərdi.
    """

    user_message = (
        "Bu modul aktiv üz-təsdiqi istisnalarının kompensasiya edici nəzarətidir "
        "və söndürülə bilməz."
    )


@dataclass(frozen=True)
class LimitView:
    """Bir limitin ekranda göstərilən tam təsviri."""

    key: str
    value: str
    description_az: str = ""
    min_value: str | None = None
    max_value: str | None = None
    #: Sətir `system_limits`-də FAKTİKİ olaraq varmı.
    #:
    #: `False` = dəyər `DEFAULT_LIMITS`-dən tamamlanıb (köhnə bazada yeni açar).
    #: Bunu `description_az`-ın içinə mətn kimi yazsaydıq, həmin sahə HƏM
    #: etiket, HƏM vəziyyət daşıyardı və ekran etiketi bazadan oxumağa
    #: keçəndə (`controllers/root_control.limit_row`) bütün belə sətirlər eyni
    #: "Defolt dəyər (bazada yazılmayıb)" adı ilə görünərdi — yəni Root
    #: parametrləri bir-birindən ayıra bilməzdi.
    is_stored: bool = True

    @property
    def is_known_key(self) -> bool:
        """Kod tərəfindən tanınan limitdirmi.

        Naməlum açar DB-də qala bilər (köhnə versiyadan qalmış). Onu
        gizlətmək əvəzinə nişanlamaq düzgündür — Root nəyin artıq
        istifadə olunmadığını görməlidir.
        """
        return self.key in {limit.value for limit in SystemLimitKey}


@dataclass(frozen=True)
class ModuleView:
    """Bir modulun toggle vəziyyəti."""

    module_key: str
    is_enabled: bool
    is_structural: bool
    description_az: str = ""

    @property
    def requires_confirmation_to_disable(self) -> bool:
        return self.is_structural and self.is_enabled


class RootControlUseCase:
    """Sistem limitləri, Feature Toggles və Permission Registry."""

    def __init__(
        self,
        *,
        limits: SystemLimits,
        toggles: FeatureToggles,
        flags: PermissionFlagRepository,
        # SEC-020: `face_exemptions` MƏCBURİ arqumentdir, `| None = None` DEYİL.
        # Defolt dəyər versəydik, kompozisiya kökündə onu ötürməyi unutmaq
        # qapını SÜKUTLA açardı — yəni qoruma "bağlıdır" görünər, faktiki
        # olaraq isə heç vaxt işləməzdi. Məcburi arqument həmin səhvi tərtib
        # zamanına (mypy) çəkir.
        face_exemptions: FaceExemptionRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._limits = limits
        self._toggles = toggles
        self._flags = flags
        self._face_exemptions = face_exemptions
        self._audit = audit
        self._clock = clock

    # --------------------------- sistem limitləri ---------------------------- #

    def list_limits(self, *, tenant_id: TenantId, actor: Employee) -> list[LimitView]:
        """Limitləri göstərir — DB-də olmayanlar DEFOLT dəyərlə tamamlanır.

        Tamamlama vacibdir: sətir yoxdursa ekran boş görünərdi, halbuki sistem
        həmin limiti defolt ilə TƏTBİQ EDİR. Root nəyin qüvvədə olduğunu
        görməlidir, nəyin DB-də yazıldığını yox.
        """
        self._require(actor, MANAGE_LIMITS_FLAG, now=self._clock.now())

        stored = {str(row.get("limit_key")): row for row in self._limits.describe(tenant_id)}
        views: list[LimitView] = []
        for key in SystemLimitKey:
            row = stored.pop(key.value, None)
            if row is None:
                views.append(
                    LimitView(
                        key=key.value,
                        value=DEFAULT_LIMITS[key],
                        is_stored=False,
                    )
                )
                continue
            views.append(
                LimitView(
                    key=key.value,
                    value=str(row.get("limit_value", DEFAULT_LIMITS[key])),
                    description_az=str(row.get("description_az") or ""),
                    min_value=self._optional_str(row.get("min_value")),
                    max_value=self._optional_str(row.get("max_value")),
                )
            )

        # Kodun tanımadığı, lakin bazada qalan açarlar — sonda, nişanlı.
        views.extend(
            LimitView(
                key=key,
                value=str(row.get("limit_value", "")),
                description_az=str(row.get("description_az") or ""),
            )
            for key, row in stored.items()
        )
        return views

    def set_limit(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        key: SystemLimitKey,
        value: str,
    ) -> LimitView:
        """Limiti dəyişir — hər dəyişiklik audit-lənir."""
        now = self._clock.now()
        self._require(actor, MANAGE_LIMITS_FLAG, now=now)

        cleaned = value.strip()
        if not cleaned:
            raise RootControlError(
                f"Limit dəyəri boş ola bilməz: {key.value}",
                user_message="Limit dəyəri boş ola bilməz.",
            )

        # DİL KODU BURADA DA YOXLANILIR — `set_language` KİFAYƏT ETMİR.
        #
        # `UI_LANGUAGE` ROOT ekranında İKİ yerdən yazıla bilir: «Dil»
        # kombinat qutusundan (`set_language`, kataloqu yoxlayır) və ÜMUMİ
        # limit siyahısından (bu metod — açar `SystemLimitKey`-dədir, yəni
        # siyahıda görünür və sərbəst mətn qəbul edir). İkinci yol
        # yoxlamasız qalsaydı, Root eyni ekranda «ru» yazıb kataloqu boş olan
        # dilə keçə bilərdi və tətbiq tərcüməsiz açarlarda qalardı —
        # `set_language`-in şərhində yazılan qadağa məhz belə yan keçilərdi.
        if key is SystemLimitKey.UI_LANGUAGE and cleaned not in AVAILABLE_UI_LANGUAGES:
            raise RootControlError(
                f"Naməlum dil kodu: {cleaned}",
                user_message="Bu dil hazırda mövcud deyil.",
                context={"language": cleaned},
            )

        previous = self._limits.get_str(tenant_id, key.value, DEFAULT_LIMITS[key])
        self._limits.set_value(tenant_id, key.value, cleaned, changed_by=actor.id)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SYSTEM_LIMIT_CHANGED",
            entity_type="system_limit",
            entity_id=key.value,
            before_state={"value": previous},
            after_state={"value": cleaned},
        )
        _audit_log.info(
            "SYSTEM_LIMIT_CHANGED",
            extra={"actor_id": str(actor.id), "key": key.value, "value": cleaned},
        )
        return LimitView(key=key.value, value=cleaned)

    def language(self, *, tenant_id: TenantId) -> str:
        """Kirayəçinin cari interfeys dili — Faza 8.1 (Root panelinin «Dil» kartı).

        Oxu yolu SƏLAHİYYƏT TƏLİB ETMİR: dil məlumatı deyil və Ayarlar ekranı
        onsuz da hər istifadəçiyə açıqdır. Yazı yolu (`set_language`) qapılıdır.
        """
        return self._limits.get_str(
            tenant_id,
            SystemLimitKey.UI_LANGUAGE.value,
            DEFAULT_LIMITS[SystemLimitKey.UI_LANGUAGE],
        )

    def set_language(self, *, tenant_id: TenantId, actor: Employee, language: str) -> str:
        """İnterfeys dilini dəyişir — YALNIZ kataloqda olan dilə.

        `AVAILABLE_UI_LANGUAGES`-də olmayan kod RƏDD EDİLİR: Root «ru» yazsa
        amma rus kataloqu boşdursa, tətbiq tərcüməsiz açarlarda qalardı —
        spesifikasiyanın «bu fazada rus dilini tərcümə etmə» sözünün kod
        qarşılığı məhz bu yoxlamadır.

        Eyni yoxlama `set_limit`-də DƏ var və bu, təkrar deyil: həmin metod
        ümumi limit siyahısından birbaşa çağırıla bilir, yəni bu qapı tək
        başına dursaydı yan keçilərdi (CLAUDE.md §5-in «hər qayda İKİ yerdə»
        prinsipi).
        """
        if language not in AVAILABLE_UI_LANGUAGES:
            raise RootControlError(
                f"Naməlum dil kodu: {language}",
                user_message="Bu dil hazırda mövcud deyil.",
                context={"language": language},
            )
        view = self.set_limit(
            tenant_id=tenant_id,
            actor=actor,
            key=SystemLimitKey.UI_LANGUAGE,
            value=language,
        )
        return view.value

    # ---------------------------- feature toggles ---------------------------- #

    def list_modules(self, *, tenant_id: TenantId, actor: Employee) -> list[ModuleView]:
        """Modul siyahısı — bazada sətri olmayan modul AÇIQ sayılır.

        Fail-safe istiqaməti budur: konfiqurasiya sətrinin olmaması bütün
        sistemi söndürməməlidir. Söndürmək AÇIQ əməliyyat olmalıdır.
        """
        self._require(actor, MANAGE_LIMITS_FLAG, now=self._clock.now())

        stored = {str(row.get("module_key")): row for row in self._toggles.describe(tenant_id)}
        views: list[ModuleView] = []
        for module in FeatureModule:
            row = stored.pop(module.value, None)
            if row is None:
                views.append(
                    ModuleView(
                        module_key=module.value,
                        is_enabled=True,
                        is_structural=module.is_structural,
                        description_az="Defolt: açıq (bazada yazılmayıb)",
                    )
                )
                continue
            views.append(
                ModuleView(
                    module_key=module.value,
                    is_enabled=bool(row.get("is_enabled", True)),
                    is_structural=bool(row.get("is_structural", module.is_structural)),
                    description_az=str(row.get("description_az") or ""),
                )
            )

        views.extend(
            ModuleView(
                module_key=key,
                is_enabled=bool(row.get("is_enabled", True)),
                is_structural=bool(row.get("is_structural", False)),
                description_az=str(row.get("description_az") or ""),
            )
            for key, row in stored.items()
        )
        return views

    def set_module_enabled(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        module_key: str,
        enabled: bool,
        confirmation: str | None = None,
    ) -> ModuleView:
        """Modulu açır/söndürür.

        Təsdiq mətninin UZUNLUĞU burada yoxlanılır, mövcudluğu isə repository
        qatında — iki yerdə eyni səbəbdən: ekran yan keçilə bilər, repository
        isə hər yol üçün son qapıdır.
        """
        now = self._clock.now()
        self._require(actor, MANAGE_LIMITS_FLAG, now=now)

        if not enabled:
            self._require_no_dependent_guarantee(tenant_id, module_key, actor=actor, now=now)

        structural = self._toggles.is_structural(tenant_id, module_key)
        if not enabled and structural:
            cleaned = normalise_decision_text(confirmation or "")
            if len(cleaned) < MIN_CONFIRMATION_LENGTH:
                _security_log.warning(
                    "STRUCTURAL_MODULE_DISABLE_BLOCKED",
                    extra={"actor_id": str(actor.id), "module": module_key},
                )
                raise StructuralModuleError(
                    f"«{module_key}» struktur-kritik moduldur — "
                    f"minimum {MIN_CONFIRMATION_LENGTH} simvolluq təsdiq tələb olunur",
                    context={"module": module_key},
                )
            confirmation = cleaned

        was_enabled = self._toggles.is_enabled(tenant_id, module_key)
        self._toggles.set_enabled(
            tenant_id,
            module_key,
            enabled=enabled,
            changed_by=actor.id,
            confirmation=confirmation,
        )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="FEATURE_TOGGLE_CHANGED",
            entity_type="feature_toggle",
            entity_id=module_key,
            before_state={"is_enabled": was_enabled},
            after_state={"is_enabled": enabled, "is_structural": structural},
            reason=confirmation,
        )
        return ModuleView(module_key=module_key, is_enabled=enabled, is_structural=structural)

    def _require_no_dependent_guarantee(
        self, tenant_id: TenantId, module_key: str, *, actor: Employee, now: datetime
    ) -> None:
        """SEC-020 — kompensasiya edici nəzarət ASILISI VARKƏN söndürülə bilməz.

        ──────────────────────────────────────────────────────────────────────
        BAĞLANAN BOŞLUQ
        ──────────────────────────────────────────────────────────────────────
        `facecontrol.md` bənd 14 üz-təsdiqi istisnasını (tibbi/fiziki səbəblə
        PIN-only) YALNIZ bir şərtlə verir: boşluq MƏCBURİ ikinci-təsdiqlə
        əvəzlənir. Həmin ikinci təsdiq `DUAL_CONTROL` modulunun axınıdır və o,
        adi (struktur-olmayan) toggle idi — yəni Root bir kliklə istisnalı
        işçini kompensasiyasız qoya bilirdi. Nəticə tərif olunmamış davranış
        idi: ya işçi əbədi bloklanardı, ya da onun PIN-i ilə İSTƏNİLƏN şəxs
        təkbaşına təsdiq alardı.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ ŞƏRTİ KİLİD, NİYƏ `is_structural = TRUE` DEYİL
        ──────────────────────────────────────────────────────────────────────
        `is_structural` variantı ciddi nəzərdən keçirildi və RƏDD EDİLDİ:

          * O, YAZILI TƏSDİQ tələb edir, SÖNDÜRMƏNİ ÖZÜNÜ dayandırmır. 6
            simvol yazan Root istisnalı işçini yenə kompensasiyasız qoyardı —
            yəni sənədləşmə əlavə olunar, zəmanət isə bərpa olunmazdı.
          * Zəmanət ŞƏRTLİDİR: aktiv istisnası olmayan kirayəçidə `DUAL_CONTROL`
            həqiqətən adi bir qatdır (manual vaxt düzəlişi həddi) və onu qlobal
            "struktur" elan etmək `is_structural`-ın mənasını seyrəldərdi.
          * Kilid ƏBƏDİ DEYİL: Root əvvəlcə istisnaları ləğv edir, sonra modulu
            söndürür. Yəni qapı bağlıdır, açarı isə Root-un öz əlindədir.

        ──────────────────────────────────────────────────────────────────────
        QAYDA İKİ YERDƏDİR (CLAUDE.md §5)
        ──────────────────────────────────────────────────────────────────────
        DB yarısı `enforce_face_exemption_compensation()` trigger-idir
        (`migrations/051`) — ekranı yan keçən birbaşa `UPDATE feature_toggles`
        də eyni cavabı alır. Üçüncü qat isə runtime-dır
        (`FaceVerificationUseCase._exempt_employee_gate`): köhnə/əlüstü
        yaradılmış vəziyyət də sükutla keçmir.
        """
        if module_key != FACE_EXEMPTION_COMPENSATING_MODULE.value:
            return
        active = self._face_exemptions.list_active(tenant_id, now=now)
        if not active:
            return
        _security_log.warning(
            "COMPENSATING_MODULE_DISABLE_BLOCKED",
            extra={
                "actor_id": str(actor.id),
                "module": module_key,
                "active_exemptions": len(active),
            },
        )
        raise CompensatingControlLockedError(
            f"«{module_key}» modulu {len(active)} aktiv Face Control istisnasının "
            f"kompensasiya edici nəzarətidir — söndürülə bilməz (facecontrol.md bənd 14)",
            user_message=(
                f"{len(active)} aktiv üz-təsdiqi istisnası var; onların kompensasiya "
                f"nəzarəti məhz bu moduldur. Modulu söndürmək üçün əvvəlcə həmin "
                f"istisnaları «Üz Təsdiqi İstisnaları» ekranından ləğv edin."
            ),
            context={"module": module_key, "active_exemptions": len(active)},
        )

    # -------------------------- permission registry -------------------------- #

    def list_flags(self, *, actor: Employee) -> list[PermissionFlag]:
        """İcazə kataloqu — matris ekranının sütun mənbəyi."""
        self._require(actor, MANAGE_PERMISSIONS_FLAG, now=self._clock.now())
        return self._flags.list_all()

    def create_flag(
        self, *, tenant_id: TenantId, actor: Employee, flag: PermissionFlag
    ) -> PermissionFlag:
        """Yeni icazə flag-i — YALNIZ `Root` (bölmə 3).

        Flag `can_manage_permissions` ilə deyil, ROLLA da qorunur: bu
        səlahiyyət `CEO`-ya verilə bilər, lakin yeni flag yaratmaq icazə
        modelinin ÖZÜNÜ dəyişir və spesifikasiya onu adbaad `Root`-a
        bağlayır ("yeni flag yaratma, YALNIZ Root").
        """
        now = self._clock.now()
        self._require(actor, MANAGE_PERMISSIONS_FLAG, now=now)

        if actor.position.effective_system_role is not SystemRole.ROOT:
            _security_log.warning(
                "PERMISSION_FLAG_CREATE_BLOCKED",
                extra={"actor_id": str(actor.id), "role": actor.position.code},
            )
            raise RootControlError(
                "Yeni icazə flag-ini YALNIZ Root yarada bilər (bölmə 3)",
                user_message="Yeni icazə yaratmaq yalnız Root üçündür.",
                context={"role": actor.position.code},
            )

        if self._flags.get(flag.code) is not None:
            raise RootControlError(
                f"Bu kodla flag artıq mövcuddur: {flag.code}",
                user_message="Bu adda icazə artıq var.",
                context={"code": flag.code},
            )

        self._flags.create(flag, created_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="PERMISSION_FLAG_CREATED",
            entity_type="permission_flag",
            entity_id=flag.code,
            after_state={
                "code": flag.code,
                "category": flag.category,
                "hardlock": flag.hardlock.name,
                "is_anti_fraud": flag.is_anti_fraud,
            },
        )
        _security_log.warning(
            "PERMISSION_FLAG_CREATED",
            extra={"actor_id": str(actor.id), "code": flag.code},
        )
        return flag

    # ------------------------------- köməkçilər ------------------------------ #

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return None if value is None else str(value)

    def _require(self, actor: Employee, flag: str, *, now: datetime) -> None:
        if not actor.has_permission(flag, now=now):
            _security_log.warning(
                "ROOT_CONTROL_DENIED",
                extra={"actor_id": str(actor.id), "flag": flag},
            )
            raise RootControlError(
                f"«{flag}» səlahiyyəti yoxdur",
                user_message="Bu bölmə üçün səlahiyyətiniz yoxdur.",
                context={"flag": flag},
            )


__all__ = [
    "MANAGE_LIMITS_FLAG",
    "MANAGE_PERMISSIONS_FLAG",
    "MIN_CONFIRMATION_LENGTH",
    "CompensatingControlLockedError",
    "LimitView",
    "ModuleView",
    "RootControlError",
    "RootControlUseCase",
    "StructuralModuleError",
]
