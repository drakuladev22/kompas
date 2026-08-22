"""Rol/vəzifə aqreqatı (spesifikasiya bölmə 3).

7 defolt sistem rolu + Root/CEO-nun yaratdığı istənilən sayda custom rol.
Hər rol bir iyerarxiya prioriteti daşıyır və bu, Strict Hierarchy Guard-ın
əsasını təşkil edir.

──────────────────────────────────────────────────────────────────────────────
GERİ ALMA (REVOKE) VERMƏK QƏDƏR HƏSSASDIR
──────────────────────────────────────────────────────────────────────────────
Uzun müddət `grant()` bütün qoruyucu qaydalardan keçirdi, `revoke()` isə sadəcə
`discard()` idi. Anti-fraud auditi bunu qüsur kimi tapdı, çünki hücum
istiqaməti simmetrik deyil:

    * VERMƏK  → hədəfin səlahiyyəti ARTIR (hardlock/anti-fraud tutur);
    * ALMAQ   → hədəfin səlahiyyəti AZALIR — və məhz bu, YUXARI pilləyə qarşı
      istifadə olunur. CEO `Root` rolundan `can_manage_permissions`-i çıxara
      bilsəydi, Root öz sistemindən kilidlənərdi; sonra həmin flag-i özünə
      qaytarmaq artıq heç kimin əlində olmazdı.

Ona görə `revoke()` İKİ qapıdan keçir — Strict Hierarchy Guard (aktor CİDDİ
ŞƏKİLDƏ aşağı pilləyə toxuna bilər) və mütləq `ROOT_ONLY` yoxlaması. Eyni iki
qapı `position_management.set_role_flags()`-də də çağırılır: use case bütün
əməliyyat üçün BİR dəfə (flag dəsti boş olsa belə), entity isə HƏR sətir üçün.

`grant()` bu parametrləri TƏLƏB ETMİR: onun qoruması `assert_grantable_to()`
ilə onsuz da işləyir və imzasını dəyişmək bütün quraşdırma yollarını
(`mappers`, seed, maket) sındırardı. İyerarxiya yoxlaması vermə yolunda
`position_management._apply_flags`-dədir — yəni qayda YENƏ İKİ yerdədir,
sadəcə birinci yer entity, ikincisi use case-dir.
"""

from __future__ import annotations

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.value_objects.authorization import (
    AuthorizationError,
    HardlockLevel,
    PermissionFlag,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.identifiers import PositionId, TenantId
from src.shared.logger import LogChannel, get_logger

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


class Position(AggregateRoot):
    """Rol (vəzifə) — sistem və ya custom.

    `is_store_tier` `is_camera_type`-ın EYNİ NAXIŞIDIR (T6): custom rol
    prioritetinə görə `effective_system_role`-da ən yaxın SİSTEM roluna
    (məs. `HR_ADMIN`) düşür, amma anti-fraud qadağası (`ANTI_FRAUD_
    FORBIDDEN_ROLES`) yalnız hərfi `MAGAZA_MENECERI`/`SATICI` KODUNU
    tanıyır. Root/CEO Mağaza Meneceri səlahiyyətli custom rol yaradıb bu
    boşluqdan `can_approve_dual_control_override` kimi flag-ləri vermək
    istəsə, `is_store_tier=True` işarəsi olmadan yoxlama onu keçirərdi.
    Bax `PermissionFlag.assert_grantable_to`-dakı `is_store_tier_role`
    şərhi — DB qarşılığı `positions.is_store_tier` (schema.sql §18).
    """

    def __init__(
        self,
        *,
        position_id: PositionId,
        code: str,
        name_az: str,
        priority: RolePriority,
        tenant_id: TenantId | None = None,
        is_system: bool = False,
        is_camera_type: bool = False,
        is_store_tier: bool = False,
        is_active: bool = True,
    ) -> None:
        super().__init__()
        if not code.strip():
            raise DomainRuleError("Rol kodu boş ola bilməz")

        self.id = position_id
        self.tenant_id = tenant_id
        self.code = code.strip().upper()
        self.name_az = name_az.strip()
        self.priority = priority
        self.is_system = is_system
        self.is_camera_type = is_camera_type
        self.is_store_tier = is_store_tier
        self.is_active = is_active
        self._granted_flags: set[str] = set()

    # ----------------------------- sistem rolu ------------------------------ #

    @property
    def system_role(self) -> SystemRole | None:
        """Kod 7 defolt roldan birinə uyğun gəlirsə həmin rolu qaytarır."""
        try:
            return SystemRole(self.code)
        except ValueError:
            return None

    @property
    def effective_system_role(self) -> SystemRole:
        """Qoruyucu qaydaların tətbiqi üçün ən yaxın sistem rolu semantikası.

        Custom rol üçün prioritetinə görə ən yaxın sistem rolu seçilir —
        beləliklə hardlock/anti-fraud qaydaları custom rollara da tətbiq olunur
        və "custom rol yaradıb qadağanı yan keçmək" yolu bağlanır.
        """
        known = self.system_role
        if known is not None:
            return known
        return _PRIORITY_TO_ROLE[self.priority]

    # ------------------------------ icazələr -------------------------------- #

    def grant(self, flag: PermissionFlag) -> None:
        """Rola flag verir — bütün qoruyucu qaydalar yoxlanılır."""
        flag.assert_grantable_to(
            self.effective_system_role,
            is_camera_type_role=self.is_camera_type,
            is_store_tier_role=self.is_store_tier,
        )
        self._granted_flags.add(flag.code)

    def revoke(self, flag: PermissionFlag, *, actor_position: Position | None = None) -> None:
        """Rola verilmiş flag-i geri alır — VERMƏK qədər qorunan yoldur.

        Args:
            flag: Geri alınan flag-in KATALOQ tərifi. Kod (`str`) kifayət
                etmirdi: `hardlock` səviyyəsi yalnız kataloqda yaşayır və
                `ROOT_ONLY` yoxlaması onsuz aparıla bilməzdi.
            actor_position: Əməliyyatı aparan istifadəçinin rolu.
                DEFOLT `None` "qorumasız keç" DEYİL — FAIL-CLOSED-dur və
                istisna atır. Səbəb: bu parametr sonradan əlavə olunub və
                unudulmuş bir çağırış nöqtəsi sükutla köhnə (qorumasız)
                davranışa qayıtsaydı, düzəliş heç nə dəyişməzdi.

        Raises:
            AuthorizationError: iyerarxiya və ya `ROOT_ONLY` qaydası pozulubsa.
        """
        self.assert_may_be_edited_by(actor_position)
        self.assert_root_only_flag_allowed(flag, actor_position=actor_position)
        self._granted_flags.discard(flag.code)

    def has_flag(self, flag_code: str) -> bool:
        return flag_code in self._granted_flags

    @property
    def granted_flags(self) -> frozenset[str]:
        return frozenset(self._granted_flags)

    # ------------------------------ iyerarxiya ------------------------------ #

    def outranks(self, other: Position) -> bool:
        """Strict Hierarchy Guard: CİDDİ ŞƏKİLDƏ yüksəkdirmi (bərabər → False)."""
        return self.priority.outranks(other.priority)

    def may_be_edited_by(self, actor_position: Position | None) -> bool:
        """`assert_may_be_edited_by`-ın SƏSSİZ variantı — siyahı süzgəci üçün.

        ────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA METOD, `try/except` DEYİL
        ────────────────────────────────────────────────────────────────────
        `assert_...` uğursuzluqda `security.log`-a XƏBƏRDARLIQ yazır və bu,
        doğrudur: kimsə qadağan olunmuş dəyişikliyə CƏHD edib. Siyahını
        süzgəcdən keçirərkən isə heç bir cəhd yoxdur — sadəcə «bu sətir
        göstərilsinmi?» sualı verilir. `try/except` işlətsəydik, matrisi
        AÇMAQ hər dəfə onlarla saxta təhlükəsizlik xəbərdarlığı yazardı və
        jurnaldakı əsl siqnal onların içində itərdi.

        Qayda TƏKRARLANMIR — eyni iki şərt burada da, orada da `outranks()`
        üzərindən oxunur.
        """
        if actor_position is None:
            return False
        if actor_position.effective_system_role is SystemRole.ROOT:
            return True
        return actor_position.outranks(self)

    def assert_may_be_edited_by(self, actor_position: Position | None) -> None:
        """STRICT HIERARCHY GUARD — bu rolun flag dəstinə kim toxuna bilər.

        `permission_guards._assert_strict_hierarchy` ilə EYNİ qaydadır, sadəcə
        hədəf İSTİFADƏÇİ yox, ROLDUR. Müqayisə primitivi təkrar yazılmır —
        mövcud `outranks()` çağırılır ki, "ciddi şəkildə aşağı" tərifi tək
        yerdə qalsın (`RolePriority.outranks`).

        SEC-006 İSTİSNASI: yalnız `Root` bərabər pillədən azaddır. Bölmə 3
        eyni pilləyə müdaxiləni QADAĞAN edir — əks halda bir `CEO` digərinin
        səlahiyyətlərini sükutla ala bilərdi. Root istisnası isə zəruridir:
        `Root` öz rolunun flag dəstini redaktə edə bilməsəydi, sistem ilk
        gündən kilidlənərdi.

        `CEO` → `Root` istiqaməti İKİ MÜSTƏQİL SƏBƏBDƏN bağlıdır və bu, qəsdən
        artıqlıqdır (defense-in-depth):
            1. PRİORİTET — `Root` (0) `CEO`-dan (1) CİDDİ ŞƏKİLDƏ yüksəkdir,
               yəni `outranks()` onsuz da `False` qaytarır. Bu, iyerarxiyanın
               TƏBİİ nəticəsidir; əvvəllər ikisi də 0 idi və qadağa yalnız
               bərabər-pillə şərtindən asılı qalırdı.
            2. HARDLOCK — `ROOT_ONLY` flag-lərinə toxunmaq
               `assert_root_only_flag_allowed`-da AYRICA bloklanır.

        Prioritet 0-lı CUSTOM rol bu istisnaya DÜŞMÜR: `effective_system_role`
        yalnız kodu `ROOT` olanı `ROOT` sayır (custom rol `CEO` semantikasına
        düşür — bax `_PRIORITY_TO_ROLE` şərhi), yəni "özümə prioritet 0-lı rol
        yaradıb Root-a toxunum" yolu bağlıdır. Belə rol həm də `Root` rolunu
        redaktə edə bilmir, çünki 0 <= 0 bərabər-pillədir.

        Raises:
            AuthorizationError: aktor naməlumdursa və ya pillə kifayət etmirsə.
        """
        if actor_position is None:
            # FAIL-CLOSED: aktoru tanımadan icazə qərarı vermək mümkün deyil.
            _security_log.warning(
                "POSITION_ACTOR_CONTEXT_MISSING",
                extra={"target_role": self.code},
            )
            raise AuthorizationError(
                f"AKTOR KONTEKSTİ YOXDUR: '{self.code}' rolunun icazələri aktor "
                f"məlum olmadan dəyişdirilə bilməz (bölmə 3)",
                context={"target_role": self.code},
            )

        if actor_position.effective_system_role is SystemRole.ROOT:
            return

        if not actor_position.outranks(self):
            _security_log.warning(
                "POSITION_HIERARCHY_BLOCKED",
                extra={
                    "actor_role": actor_position.code,
                    "actor_priority": actor_position.priority.name,
                    "target_role": self.code,
                    "target_priority": self.priority.name,
                },
            )
            raise AuthorizationError(
                f"STRICT HIERARCHY GUARD: yalnız CİDDİ ŞƏKİLDƏ aşağı pilləli rolun "
                f"icazələrinə toxunmaq olar (aktor={actor_position.priority.name}, "
                f"hədəf={self.priority.name})",
                user_message=("Bu rol sizinlə eyni və ya daha yüksək səlahiyyət pilləsindədir."),
                context={
                    "actor_role": actor_position.code,
                    "target_role": self.code,
                },
            )

    def assert_root_only_flag_allowed(
        self, flag: PermissionFlag, *, actor_position: Position | None
    ) -> None:
        """MÜTLƏQ `ROOT_ONLY` YOXLAMASI — iyerarxiyadan AYRI və ondan asılı deyil.

        İki şərt eyni anda ödənməlidir:
            1. əməliyyatı `Root` aparır (SEC-006 istisnası burada TƏTBİQ
               OLUNMUR — bu, pillə müqayisəsi deyil, mütləq sahiblik qaydasıdır);
            2. flag `Root` rolunda qalır (başqa rola nə verilir, nə də oradan
               götürülür — `ROOT_ONLY` flag orada ümumiyyətlə olmamalıdır).

        NİYƏ LİTERAL SİYAHI YAZILMIR — Bu qayda üçün ən aşkar yazılış
        `{"can_manage_permissions", "can_manage_system_limits", ...}` sabit
        dəsti olardı və RƏDD EDİLİB. Həmin dörd flag onsuz da
        `permission_flags.hardlock_level = 1` ilə kataloqda elan olunub və
        `HardlockLevel.ROOT_ONLY`-yə uyğun gəlir. Sabit siyahı ÜÇÜNCÜ mənbə
        yaradardı (kataloq + DB trigger + kod), CLAUDE.md §5 isə qaydanın MƏHZ
        İKİ yerdə — domendə və DB trigger-ində — olmasını tələb edir. Root yeni
        `ROOT_ONLY` flag yaratdıqda (Permission Registry) siyahı arxada qalar və
        yeni flag sükutla qorumasız buraxılardı. Ona görə qərar kataloqdan
        gələn `flag.hardlock` üzərində verilir — yoxlama isə YENƏ DƏ ayrı və
        şərtsizdir.

        Raises:
            AuthorizationError: aktor `Root` deyilsə və ya hədəf rol `Root` deyilsə.
        """
        if flag.hardlock is not HardlockLevel.ROOT_ONLY:
            return

        actor_role = actor_position.effective_system_role if actor_position is not None else None
        actor_code = actor_position.code if actor_position is not None else None

        if actor_role is not SystemRole.ROOT:
            _security_log.warning(
                "ROOT_ONLY_FLAG_BLOCKED",
                extra={"flag": flag.code, "actor_role": actor_code, "target_role": self.code},
            )
            raise AuthorizationError(
                f"HARDLOCK (səviyyə {flag.hardlock.value}): '{flag.code}' flag-inə "
                f"YALNIZ Root toxuna bilər — verilməsi də, geri alınması da "
                f"(bölmə 3, dörd-səviyyəli hardlock)",
                user_message="Bu icazəni yalnız Root dəyişdirə bilər.",
                context={"flag": flag.code, "actor_role": actor_code},
            )

        if self.effective_system_role is not SystemRole.ROOT:
            _security_log.warning(
                "ROOT_ONLY_FLAG_BLOCKED",
                extra={"flag": flag.code, "actor_role": actor_code, "target_role": self.code},
            )
            raise AuthorizationError(
                f"HARDLOCK (səviyyə {flag.hardlock.value}): '{flag.code}' flag-i "
                f"yalnız Root rolunda ola bilər — '{self.code}' roluna əlavə "
                f"edilə və oradan götürülə bilməz (bölmə 3)",
                user_message="Bu icazə yalnız Root rolunda saxlanılır.",
                context={"flag": flag.code, "target_role": self.code},
            )

        # ROOT ÖZÜ ETSƏ BELƏ İZ QALIR. Bu, sistemin ən həssas dörd flag-idir və
        # "kim, nə vaxt toxundu" sualı insidentdə ilk soruşulandır. Audit sətri
        # use case-də (`POSITION_FLAGS_UPDATED`) yazılır; buradakı xəbərdarlıq
        # isə entity səviyyəsindədir və use case yan keçilsə belə qalır.
        _security_log.warning(
            "ROOT_ONLY_FLAG_TOUCHED",
            extra={"flag": flag.code, "actor_role": actor_code, "target_role": self.code},
        )

    def deactivate(self) -> None:
        if self.is_system:
            raise DomainRuleError(
                f"Sistem rolu '{self.code}' deaktiv edilə bilməz",
                user_message="Sistem rolları silinə və ya deaktiv edilə bilməz.",
            )
        self.is_active = False

    def __repr__(self) -> str:
        return f"Position(code={self.code}, priority={self.priority.name})"


#: CUSTOM rolun prioritetindən ən yaxın SİSTEM rolu semantikası.
#:
#: ──────────────────────────────────────────────────────────────────────────
#: `RolePriority.ROOT` QƏSDƏN `SystemRole.CEO`-YA XƏRİTƏLƏNİR
#: ──────────────────────────────────────────────────────────────────────────
#: Root/CEO prioritet ayrılığından sonra ən aşkar yazılış
#: `RolePriority.ROOT: SystemRole.ROOT` olardı və RƏDD EDİLİB — o, birbaşa
#: səlahiyyət artırması yolu açardı:
#:
#:   * `assert_may_be_edited_by` `Root` semantikasına BƏRABƏR-PİLLƏ
#:     istisnası verir. Prioritet 0-lı custom rol `ROOT` sayılsaydı, onu
#:     daşıyan istifadəçi HƏQİQİ `Root` rolunun flag dəstini redaktə edə
#:     bilərdi.
#:   * `assert_root_only_flag_allowed` aktorun `ROOT` olmasını tələb edir —
#:     yəni həmin custom rol `can_manage_permissions` /
#:     `can_manage_system_limits` flag-lərinə də toxuna bilərdi.
#:   * `HardlockLevel.ROOT_ONLY.allows()` həmin flag-lərin custom rola
#:     VERİLMƏSİNƏ icazə verərdi.
#:
#: Üstəlik DB yarısı ilə fərq yaranardı: `enforce_position_flag_hierarchy()`
#: (miqrasiya 046) və `enforce_hierarchy_guard()` (schema.sql §18) Root
#: istisnasını rol KODU ilə (`v_actor_code = 'ROOT'`) verir, prioritetlə yox.
#: İki qatın fərqli qərar verməsi CLAUDE.md §5-in birbaşa pozuntusudur.
#:
#: Ona görə qayda belədir: prioritet 0 pilləsi `Root`-a AİDDİR, lakin həmin
#: pillədə yaradılan custom rol ən çoxu `CEO` səlahiyyət semantikasını alır.
#: `Root` YALNIZ kodu `ROOT` olan rolda mövcuddur (`system_role` yolu).
_PRIORITY_TO_ROLE: dict[RolePriority, SystemRole] = {
    RolePriority.ROOT: SystemRole.CEO,
    RolePriority.EXECUTIVE: SystemRole.CEO,
    RolePriority.ADMIN: SystemRole.ADMIN,
    RolePriority.OPERATIONAL: SystemRole.HR_ADMIN,
    RolePriority.STAFF: SystemRole.SELLER,
}


__all__ = ["Position"]
