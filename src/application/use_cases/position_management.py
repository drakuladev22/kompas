"""Custom rol/vəzifə idarəetməsi — `can_manage_positions` (bölmə 3) — Faza 5.

    "Sistem 7 defolt rola əlavə olaraq, Root/CEO-ya **istənilən sayda xüsusi
     (custom) rol/vəzifə yaratmaq** imkanı verir (məs. «Anbar Nəzarətçisi»,
     «Bölgə Meneceri») — Discord-da custom rol yaratmaq kimi."

──────────────────────────────────────────────────────────────────────────────
İKİ FLAG, İKİ FƏRQLİ İŞ (QARIŞDIRILMAMALIDIR)
──────────────────────────────────────────────────────────────────────────────
    `can_manage_permissions`  → YENİ FLAG yaratmaq. YALNIZ `Root`.
                                (`root_control.py` — Permission Registry)
    `can_manage_positions`    → MÖVCUD flag-lərdən YENİ ROL tərtib etmək.
                                `Root` VƏ `CEO`.

Bu modul İKİNCİSİDİR. Fərq bölmə 3-də açıq yazılıb: "CEO mövcud flag-lərdən
yeni ROL təşkil edə bilər, sadəcə yeni FLAG yarada bilməz".

──────────────────────────────────────────────────────────────────────────────
CUSTOM ROL QADAĞANI YAN KEÇƏ BİLMİR
──────────────────────────────────────────────────────────────────────────────
Ən aşkar hücum yolu budur: "Mağaza_Meneceri kamera flag-i ala bilmirsə, ona
kamera flag-i olan CUSTOM rol verərəm". Bu bağlıdır və dörd qatda:

    1. `Position.effective_system_role` — custom rol prioritetinə görə ən yaxın
       sistem rolu kimi qiymətləndirilir, yəni prioritet 3-lü (OPERATIONAL)
       custom rol operativ rol qaydalarına tabedir. Prioritet 0-lı custom rol
       isə `Root` YOX, `CEO` semantikasına düşür (bax `_PRIORITY_TO_ROLE`).
    2. `PermissionFlag.assert_grantable_to()` — hardlock + anti-fraud.
    3. `is_camera_type` bayrağı — kamera flag-ləri YALNIZ açıq şəkildə
       "kamera-tipli" işarələnmiş rollarda ola bilər (bölmə 3).
    4. `is_store_tier` bayrağı (T6) — `is_camera_type`-ın GÜZGÜSÜ: anti-fraud
       flag-lər YALNIZ açıq şəkildə "mağaza-pilləli" (Mağaza Meneceri
       ekvivalenti) işarələnmiş rollarda ola bilməz. Bu bayraq olmadan CEO
       "Filial_Məsulu" adlı prioritet-3 custom rol yaradıb Mağaza Menecerini
       ora köçürə bilərdi — `effective_system_role` onu `HR_Admin` sayardı
       (kod `STORE_MANAGER` deyil) və `ANTI_FRAUD_FORBIDDEN_ROLES` süzgəci
       yan keçilərdi.

Bu modul həmin qatları ÇAĞIRIR, təkrar yazmır.

──────────────────────────────────────────────────────────────────────────────
KAMERA-TİPLİ ROL YARATMAQ NİYƏ ƏLAVƏ ŞƏRTLƏ MƏHDUDDUR
──────────────────────────────────────────────────────────────────────────────
`is_camera_type=True` custom rol praktikada `Kamera_Nəzarətçisi`-nin
ekvivalentidir və maliyyə nəticəli səlahiyyət daşıya bilər. Ona görə onu
yalnız prioritet ≤ OPERATIONAL (3) səviyyəsində yaratmağa icazə verilir:
`Satıcı` pilləsində (4) kamera-tipli rol yaratmaq, satıcıya cərimə yazma
hüququ verməyin dolayı yolu olardı.

Hədd SİMVOLLA (`RolePriority.OPERATIONAL`) yazılır, ədədlə yox — Root/CEO
prioritet ayrılığı bütün dəyərləri bir vahid sürüşdürdü və simvol yazılışı bu
sürüşmədən heç nə hiss etmədi. DB qarşılığı isə ədəddir
(`chk_camera_role_priority`) və miqrasiya 048 onu 2-dən 3-ə qaldırır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    AuthorizationError,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import new_position_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        PermissionFlagRepository,
        PositionRepository,
    )
    from src.domain.value_objects.authorization import PermissionFlag
    from src.domain.value_objects.identifiers import PositionId, TenantId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

MANAGE_POSITIONS_FLAG = "can_manage_positions"

MIN_ROLE_NAME_LENGTH = 2
MAX_ROLE_NAME_LENGTH = 80

#: Kamera-tipli custom rol ən aşağı bu pillədə ola bilər (modul başlığına bax).
MAX_CAMERA_ROLE_PRIORITY = RolePriority.OPERATIONAL


class PositionManagementError(KompasOSError):
    """Rol əməliyyatı yerinə yetirilə bilmədi."""

    user_message = "Rol əməliyyatı icra edilə bilmədi."


class PositionNotFoundError(PositionManagementError):
    user_message = "Rol tapılmadı."


@dataclass(frozen=True)
class RoleDraft:
    """İcazə Matrisi ekranındakı "Yeni rol" formasının məzmunu."""

    code: str
    name_az: str
    priority: RolePriority
    is_camera_type: bool = False
    #: `is_camera_type`-ın GÜZGÜSÜ (T6) — mağaza-pilləli (Mağaza Meneceri
    #: ekvivalenti) custom rol açıq işarələnir, əks halda anti-fraud vəzifə
    #: ayrılığı yalnız `STORE_MANAGER`/`SELLER` KODUNU tanıyır və custom rol
    #: onu yan keçə bilər (bax modul başlığı, dördüncü qat).
    is_store_tier: bool = False
    #: Rola dərhal veriləcək flag kodları (boş da ola bilər).
    flag_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleSummary:
    """Matris ekranının sol panelindəki sətir."""

    position: Position
    is_editable: bool
    flag_count: int


class PositionManagementUseCase:
    """Custom rol yaratma/redaktə — İcazə Matrisi ekranının arxa tərəfi."""

    def __init__(
        self,
        *,
        positions: PositionRepository,
        flags: PermissionFlagRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._positions = positions
        self._flags = flags
        self._audit = audit
        self._clock = clock

    # -------------------------------- baxış ---------------------------------- #

    def list_roles(self, *, tenant_id: TenantId, actor: Employee) -> list[RoleSummary]:
        """Aktorun TOXUNA BİLDİYİ rollar — sistem rolları ayrıca işarələnir.

        Sistem rolu SİLİNMİR/DEAKTİV EDİLMİR (`Position.deactivate` bunu
        bloklayır), lakin ona flag vermək/almaq mümkündür — bölmə 3-dəki
        "rol-defolt" modeli məhz bunu nəzərdə tutur.

        ──────────────────────────────────────────────────────────────────────
        ÖZÜNDƏN YUXARI ROL SİYAHIDA ÜMUMİYYƏTLƏ GÖRÜNMÜR
        ──────────────────────────────────────────────────────────────────────
        Əvvəl bu metod BÜTÜN rolları qaytarırdı və nəticə istifadəçi hesabatı
        ilə üzə çıxdı: «CEO Root-un icazə matrisini dəyişə bilir». Yazma
        əslində BLOKLANIRDI (`set_role_flags` → `assert_may_be_edited_by`),
        lakin ekran `Root` sətrini redaktə oluna bilən kimi göstərirdi —
        istifadəçi xanaları işarələyir, «Yadda Saxla» basır və yalnız o an
        rədd cavabı alırdı.

        Bu, bölmə 3-ün «GÖRMƏK = SƏLAHİYYƏTİN OLMASI» prinsipinin pozulması
        idi: «icazəsiz maddə boz görünmür, tamamilə yoxdur». Süzgəc həmin
        prinsipi rol siyahısına da tətbiq edir.

        ROOT/DEVELOPER PİLLƏSİ MÜŞTƏRİYƏ AİD DEYİL: `Root` təchizatçının
        (developer) pilləsidir, `CEO` isə müştərinin ən yüksək hesabıdır.
        İkisinin ayrılması qəsdlidir — müştəri öz sistemində təchizatçının
        səlahiyyətlərini nə görməli, nə də dəyişməlidir.

        Süzgəc TƏHLÜKƏSİZLİK QAPISI DEYİL, onun GÖRÜNTÜSÜDÜR. Əsl qapı
        `Position.assert_may_be_edited_by()`-dədir və ekranı yan keçən kod da
        ona tabedir — bu, `CLAUDE.md` §5-in «hər qayda iki yerdə» prinsipinin
        eyni tətbiqidir.
        """
        self._require_permission(actor)
        return [
            RoleSummary(
                position=position,
                is_editable=not position.is_system,
                flag_count=len(position.granted_flags),
            )
            for position in self._positions.list_for_tenant(tenant_id)
            if position.may_be_edited_by(actor.position)
        ]

    # ------------------------------- yaratma --------------------------------- #

    def create_role(self, *, tenant_id: TenantId, actor: Employee, draft: RoleDraft) -> Position:
        """Yeni custom rol yaradır və seçilmiş flag-ləri təyin edir."""
        self._require_permission(actor)
        code = _clean_code(draft.code)
        name = _clean_name(draft.name_az)

        if _is_system_code(code):
            raise PositionManagementError(
                f"'{code}' sistem rol kodudur — custom rol bu adı daşıya bilməz",
                user_message="Bu ad sistem rolları üçün ayrılıb, başqa ad seçin.",
                context={"code": code},
            )
        if self._positions.get_by_code(tenant_id, code) is not None:
            raise PositionManagementError(
                f"'{code}' kodlu rol artıq mövcuddur",
                user_message="Bu adda rol artıq var.",
                context={"code": code},
            )
        if draft.is_camera_type and draft.priority > MAX_CAMERA_ROLE_PRIORITY:
            raise PositionManagementError(
                "Kamera-tipli rol ən aşağı operativ pillədə (3) ola bilər",
                user_message=(
                    "Kamera-tipli rol yalnız operativ və ya daha yüksək pillədə yaradıla bilər."
                ),
                context={"priority": draft.priority.name},
            )

        position = Position(
            position_id=new_position_id(),
            code=code,
            name_az=name,
            priority=draft.priority,
            tenant_id=tenant_id,
            is_system=False,
            is_camera_type=draft.is_camera_type,
            is_store_tier=draft.is_store_tier,
        )
        # ──────────────────────────────────────────────────────────────────────
        # YARADILAN ROL AKTORDAN CİDDİ ŞƏKİLDƏ AŞAĞI OLMALIDIR
        # ──────────────────────────────────────────────────────────────────────
        # Bu yoxlama ƏVVƏL YOX İDİ və boşluq praktikdə belə görünürdü: `CEO`
        # `can_manage_positions` ilə ÖZ pilləsində (və ya `Root` pilləsində)
        # custom rol yarada bilirdi. Flag-lər `_apply_flags`-də qorunurdu
        # (aktor özündə olmayanı verə bilmir), lakin İYERARXİYA qorunmurdu —
        # nəticədə sistemdə aktordan yuxarı, sonra isə HEÇ KİMİN (Root-dan
        # başqa) idarə edə bilmədiyi rol yaranırdı.
        #
        # Qayda TƏKRAR YAZILMIR: `assert_may_be_edited_by` çağırılır, yəni
        # «yarada bildiyim rol = sonradan idarə edə bildiyim rol». İki ayrı
        # şərt yazsaydıq, biri dəyişəndə digəri sükutla geridə qalardı.
        position.assert_may_be_edited_by(actor.position)

        granted = self._apply_flags(position, draft.flag_codes, actor=actor)
        self._positions.save(position)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_CREATED",
            entity_type="positions",
            entity_id=position.id,
            after_state={
                "code": code,
                "name_az": name,
                "priority": int(draft.priority),
                "is_camera_type": draft.is_camera_type,
                "is_store_tier": draft.is_store_tier,
                "flags": sorted(granted),
            },
        )
        return position

    # ------------------------------- redaktə --------------------------------- #

    def set_role_flags(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        position_id: PositionId,
        flag_codes: tuple[str, ...],
    ) -> Position:
        """Rolun flag dəstini TAM əvəzləyir (checkbox-grid-in "Yadda saxla"-sı).

        Fərqli yanaşma (yalnız dəyişənləri göndərmək) ekranı vəziyyət
        izləməyə məcbur edərdi; matris onsuz da bütün xanaları göndərir.

        ──────────────────────────────────────────────────────────────────────
        ÜÇ QAPI, ÜÇÜ DƏ AYRIDIR
        ──────────────────────────────────────────────────────────────────────
        1. `can_manage_positions` — ÜMUMİYYƏTLƏ rol redaktə edə bilirmi;
        2. STRICT HIERARCHY GUARD — MƏHZ BU rolu redaktə edə bilirmi;
        3. Self-Escalation + hardlock + anti-fraud — MƏHZ BU flag-i verə
           bilirmi (`_apply_flags` → `Position.grant`).

        Uzun müddət yalnız 1 və 3 var idi. Nəticə: `can_manage_positions`
        sahibi (defolt `Root` VƏ `CEO`) ÖZ pilləsindən yuxarı rolun flag
        dəstini redaktə edə bilirdi — praktikada CEO `Root` rolundan hardlock
        flag-lərini çıxara bilərdi. Qapı 3 bunu tutmurdu, çünki o, VERİLƏN
        flag-ə baxır; hücum isə GERİ ALMA yolundadır və orada heç bir yoxlama
        yox idi.

        Yoxlama BURADA da, `Position.revoke()` içində də var. Təkrar deyil:
        bura BÜTÜN əməliyyat üçün bir dəfə işləyir (flag dəsti boş olsa belə,
        yəni "hamısını sil" halında da), entity isə hər sətir üçün — ekranı
        yan keçən kod birbaşa `revoke()` çağırsa qapı yenə bağlıdır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ "HAMISINI GERİ AL, HAMISINI YENİDƏN VER" DEYİL (QA-FULL FAZA 3)
        ──────────────────────────────────────────────────────────────────────
        Əvvəlki yazılış BÜTÜN mövcud flag-ləri əvvəlcə geri alır, sonra
        göndərilən BÜTÜN dəsti yenidən verirdi — "vermək" yolu isə hər flag
        üçün Self-Escalation Guard-dan (`actor.has_permission`) keçirdi.
        `PermissionMatrixScreen.collected()` isə disabled/toxunulmamış xanaları
        DA "checked" kimi göndərir (D3 qərarı: deaktiv xana matrisdən DÜŞMÜR,
        əks halda rolun mövcud icazəsi sükutla silinərdi). Nəticə: rolda ARTIQ
        olan, lakin admin-in ÖZÜNDƏ OLMAYAN bir flag varsa (onu vaxtilə başqa,
        daha yüksək admin vermişdi), admin həmin xanaya HEÇ TOXUNMASA BELƏ
        Self-Escalation Guard BÜTÜN yazını rədd edirdi — admin ÖZ tam icazəli
        olduğu, TAMAM ƏLAQƏSİZ bir flag-i belə əlavə edə bilmirdi.

        Düzəliş: `before` (rolun HAZIRKI dəsti) və `requested` (ekranın
        göndərdiyi TAM dəst) arasındakı FƏRQ hesablanır.
            * `to_remove` (əvvəl var idi, indi yoxdur) → `Position.revoke()`,
              STRICT HIERARCHY + mütləq ROOT_ONLY yoxlanılır (dəyişmir),
              Self-Escalation TƏTBİQ OLUNMUR — silmək səlahiyyəti ARTIRMIR
              (aşağıdakı şərhə bax).
            * `newly_added` (indi əlavə olunur) → Self-Escalation Guard
              TƏTBİQ OLUNUR: aktor ÖZÜNDƏ OLMAYAN flag-i əlavə EDƏ BİLMƏZ.
            * Toxunulmayan qalan flag-lər (həm `before`-də, həm `requested`-də)
              YENİDƏN GERİ ALINMIR — Self-Escalation onlara tətbiq olunmur,
              çünki heç bir yeni səlahiyyət verilmir. Onlar YENƏ DƏ
              `_apply_flags`-ə göndərilir (hardlock/anti-fraud/ROOT_ONLY
              re-validasiyası qalır, bax `test_root_touching_a_root_only_
              flag_leaves_a_security_warning`) — YALNIZ mülkiyyət yoxlaması
              güzəştə düşür.

        SİLMƏ NİYƏ SELF-ESCALATION-A TABE DEYİL: Self-Escalation Guard
        səlahiyyət ARTIMININ qarşısını alır ("özündə olmayanı VER"). Flag
        SİLMƏK səlahiyyəti azaldır, artırmır — aktor özündə olmayan bir
        flag-i rolda SAXLAMAQ deyil, MƏHZ ÇIXARMAQ istəyirsə, bu, hədəf rolu
        aktorun ÖZ pilləsindən zəiflədir, güclətmir. Buna görə `revoke()`
        Self-Escalation ownership yoxlaması APARMIR (əvvəldən belə idi) —
        YALNIZ Strict Hierarchy + mütləq ROOT_ONLY tətbiq olunur, ikisi də
        DƏYİŞMİR.
        """
        self._require_permission(actor)
        position = self._require_position(position_id)
        # (a) STRICT HIERARCHY GUARD — hədəf rol aktordan CİDDİ ŞƏKİLDƏ aşağı
        #     olmalıdır (SEC-006: bərabər pillə də bloklanır, yalnız Root azaddır).
        position.assert_may_be_edited_by(actor.position)
        before = set(position.granted_flags)
        requested = set(flag_codes)

        for code in sorted(before - requested):
            # (b) MÜTLƏQ ROOT_ONLY yoxlaması `revoke()`-un içindədir və
            #     iyerarxiya nəticəsindən ASILI DEYİL. Kataloq tərifi ona görə
            #     ötürülür ki, `hardlock` səviyyəsi yalnız orada yaşayır.
            position.revoke(self._require_flag(code), actor_position=actor.position)

        self._apply_flags(
            position,
            tuple(sorted(requested)),
            actor=actor,
            newly_added=requested - before,
        )
        self._positions.save(position)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_FLAGS_UPDATED",
            entity_type="positions",
            entity_id=position.id,
            before_state={"flags": sorted(before)},
            after_state={"flags": sorted(position.granted_flags)},
        )
        return position

    def rename_role(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        position_id: PositionId,
        name_az: str,
    ) -> Position:
        """Rolun görünən adını dəyişir — kod TOXUNULMAZ qalır.

        Kod dəyişməsi mümkün deyil, çünki `position_permissions` və audit
        sətirləri ona istinad edir; ad isə sadəcə etiketdir.
        """
        self._require_permission(actor)
        position = self._require_position(position_id)
        if position.is_system:
            raise PositionManagementError(
                f"Sistem rolu '{position.code}' adlandırıla bilməz",
                user_message="Sistem rollarının adı dəyişdirilə bilməz.",
                context={"code": position.code},
            )

        before = position.name_az
        position.name_az = _clean_name(name_az)
        self._positions.save(position)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_RENAMED",
            entity_type="positions",
            entity_id=position.id,
            before_state={"name_az": before},
            after_state={"name_az": position.name_az},
        )
        return position

    def deactivate_role(
        self, *, tenant_id: TenantId, actor: Employee, position_id: PositionId
    ) -> Position:
        """Custom rolu deaktiv edir (sistem rolları üçün istisna atır)."""
        self._require_permission(actor)
        position = self._require_position(position_id)

        position.deactivate()
        self._positions.save(position)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="POSITION_DEACTIVATED",
            entity_type="positions",
            entity_id=position.id,
            before_state={"is_active": True},
            after_state={"is_active": False, "code": position.code},
        )
        return position

    # ------------------------------- köməkçi --------------------------------- #

    def _apply_flags(
        self,
        position: Position,
        flag_codes: tuple[str, ...],
        *,
        actor: Employee,
        newly_added: set[str] | None = None,
    ) -> set[str]:
        """Flag-ləri rola verir; qadağan olunan hər cəhd istisna atır.

        SELF-ESCALATION GUARD (bölmə 3): aktor YALNIZ ÖZÜNDƏ AKTİV OLAN
        flag-ləri rola verə bilər. Bu, `permission_guards.py`-dakı fərdi
        override qaydasının rol tərəfindəki qarşılığıdır — onsuz CEO özündə
        olmayan bir flag-i custom rola qoyub həmin rolu özünə təyin edə bilərdi.

        `newly_added` (QA-FULL Faza 3 düzəlişi): mülkiyyət yoxlaması YALNIZ bu
        dəstdəki kodlara tətbiq olunur. `None` — `create_role` çağırış
        nöqtəsindəki DEFOLT — "bütün `flag_codes` yenidir" deməkdir, çünki
        təzə rolda ƏVVƏLKİ flag yoxdur, hamısı həqiqətən YENİ verilir.
        `set_role_flags` isə `requested - before` ötürür: rolda ARTIQ olan,
        admin-in TOXUNMADIĞI flag (D3: disabled xana da "checked" göndərilir)
        bu yoxlamadan keçmir — əks halda tam əlaqəsiz, icazəli bir dəyişiklik
        belə rədd edilirdi (bax `set_role_flags` başlığı).

        STRICT HIERARCHY GUARD burada da çağırılır, çünki bu metod İKİ yoldan
        gəlir: `set_role_flags` (orada onsuz da yoxlanılıb) və `create_role`.
        İkincisi olmasaydı boşluq açıq qalardı — aktor öz pilləsində (və ya
        ondan yuxarıda) YENİ rol yaradıb ona flag doldura bilərdi, halbuki
        `position_permissions` üzərindəki DB trigger-i həmin sətri rədd edərdi.
        İki qatın FƏRQLİ qərar verməsi ən pis haldır: ekran "yazıldı" deyər,
        baza isə anlaşılmaz `psycopg` xətası qaytarardı.
        """
        now = self._clock.now()
        applied: set[str] = set()
        position.assert_may_be_edited_by(actor.position)
        escalation_checked = flag_codes if newly_added is None else newly_added

        for code in flag_codes:
            flag = self._require_flag(code)
            if code in escalation_checked and not actor.has_permission(code, now=now):
                _security_log.warning(
                    "POSITION_SELF_ESCALATION_BLOCKED",
                    extra={"actor_id": str(actor.id), "flag": code},
                )
                raise AuthorizationError(
                    f"SELF-ESCALATION: özünüzdə olmayan '{code}' flag-ini rola verə bilməzsiniz",
                    context={"actor_id": str(actor.id), "flag": code},
                )
            # MÜTLƏQ ROOT_ONLY: `grant()`-dakı hardlock yoxlaması yalnız HƏDƏF
            # roluna baxır, bu isə AKTORU da yoxlayır (CEO Root rolunda belə
            # bir flag-ə toxuna bilməz) və hər iki istiqamətdə — verəndə də,
            # alanda da — eyni qaydadır.
            position.assert_root_only_flag_allowed(flag, actor_position=actor.position)
            # Hardlock + anti-fraud + kamera qaydaları burada işə düşür.
            position.grant(flag)
            applied.add(code)

        return applied

    def _require_flag(self, code: str) -> PermissionFlag:
        """Kataloq tərifi — `hardlock` səviyyəsinin YEGANƏ mənbəyi.

        Kataloqda olmayan koda "hardlock yoxdur" deyə bilmərik: bu, qorumasız
        keçid olardı. Kodun kataloqda olması onsuz da DB-də məcburidir
        (`position_permissions.flag_code` → `permission_flags(code)` FK), yəni
        buraya düşən naməlum kod məlumat pozulmasıdır və aydın istisna ilə
        dayandırılır.
        """
        flag = self._flags.get(code)
        if flag is None:
            raise PositionManagementError(
                f"'{code}' icazə flag-i kataloqda yoxdur",
                user_message="Seçilmiş icazə mövcud deyil.",
                context={"flag": code},
            )
        return flag

    def _require_position(self, position_id: PositionId) -> Position:
        position = self._positions.get(position_id)
        if position is None:
            raise PositionNotFoundError("Rol tapılmadı", context={"position_id": str(position_id)})
        return position

    def _require_permission(self, actor: Employee) -> None:
        if not actor.has_permission(MANAGE_POSITIONS_FLAG, now=self._clock.now()):
            _security_log.warning(
                "POSITION_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_POSITIONS_FLAG},
            )
            raise AuthorizationError(
                f"«{MANAGE_POSITIONS_FLAG}» səlahiyyəti yoxdur — rol idarəetməsi "
                f"yalnız Root/CEO-dadır (bölmə 3)",
                context={"actor_id": str(actor.id)},
            )


def _clean_code(raw: str) -> str:
    cleaned = "_".join(raw.strip().upper().split())
    if not cleaned:
        raise PositionManagementError(
            "Rol kodu boş ola bilməz", user_message="Rol adı boş ola bilməz."
        )
    return cleaned


def _clean_name(raw: str) -> str:
    cleaned = " ".join(raw.split())
    if len(cleaned) < MIN_ROLE_NAME_LENGTH:
        raise PositionManagementError(
            f"Rol adı minimum {MIN_ROLE_NAME_LENGTH} simvol olmalıdır",
            user_message="Rol adı çox qısadır.",
        )
    if len(cleaned) > MAX_ROLE_NAME_LENGTH:
        raise PositionManagementError(
            f"Rol adı maksimum {MAX_ROLE_NAME_LENGTH} simvol ola bilər",
            user_message="Rol adı çox uzundur.",
        )
    return cleaned


def _is_system_code(code: str) -> bool:
    try:
        SystemRole(code)
    except ValueError:
        return False
    return True


__all__ = [
    "MANAGE_POSITIONS_FLAG",
    "MAX_CAMERA_ROLE_PRIORITY",
    "PositionManagementError",
    "PositionManagementUseCase",
    "PositionNotFoundError",
    "RoleDraft",
    "RoleSummary",
]
