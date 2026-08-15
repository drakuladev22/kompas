"""İcazə sisteminin value object-ləri (spesifikasiya bölmə 3).

Burada Discord-tərzi icazə modelinin DƏYİŞMƏZ QAYDALARI kodlaşdırılır:

* **İyerarxiya prioriteti** — `Root`=0, `CEO`=1, `Admin`=2, operativ rollar=3,
  `Satıcı`=4. Kiçik rəqəm = yüksək səlahiyyət.
* **Dörd-səviyyəli hardlock** — hansı flag-in kimə verilə biləcəyi.
* **Anti-fraud vəzifə ayrılığı** — kamera flag-ləri heç vaxt
  `Mağaza_Meneceri`/`Satıcı`-ya verilmir; təsdiq flag-i isə kamera roluna
  verilmir (SEC-001).

Bu qaydalar `docs/security_decisions.md`-də HARDCODED elan olunub və Feature
Toggle ilə söndürülə bilməz. DB tərəfində eyni qaydalar trigger kimi təkrarlanır
(defense-in-depth, `schema.sql` §18).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final

from src.shared.exceptions import KompasOSError


class AuthorizationError(KompasOSError):
    """İcazə qaydası pozuldu."""

    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


# --------------------------------------------------------------------------- #
# İyerarxiya
# --------------------------------------------------------------------------- #


class RolePriority(IntEnum):
    """Rol iyerarxiyası — KİÇİK rəqəm DAHA YÜKSƏK səlahiyyət deməkdir.

    Spesifikasiya bölmə 3: "`Root` = tək başına ən üst pillə (0) → `CEO` =
    Root-dan DƏRHAL aşağı, AYRI pillə (1) → `Admin` = CEO-dan bir pillə aşağı
    (2) → HR_Admin/Mağaza_Meneceri/Kamera_Nəzarətçisi = operativ rollar (3) →
    Satıcı/digər personel = ən aşağı pillə (4)."

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `Root` VƏ `CEO` AYRI PİLLƏDƏDİR (KONSEPTUAL DÜZƏLİŞ)
    ──────────────────────────────────────────────────────────────────────────
    Uzun müddət ikisi də `EXECUTIVE = 0` idi və nəticə iyerarxiyanın ÖZ
    mənasını pozurdu: `CEO` `Root` ilə BƏRABƏR pillədə sayılırdı. "CEO Root-un
    icazələrinə toxuna bilmir" qaydası yalnız `ROOT_ONLY` hardlock-u və
    `assert_may_be_edited_by`-dakı bərabər-pillə şərti sayəsində işləyirdi —
    yəni İYERARXİYANIN TƏBİİ NƏTİCƏSİ DEYİL, əlavə qapının yan təsiri idi.
    Həmin qapının biri açıq qalsaydı (məs. hardlock səviyyəsi 1-dən 2-yə
    düşsəydi), CEO Root-un flag dəstinə toxuna bilərdi.

    İndi `Root` (0) `CEO`-dan (1) CİDDİ ŞƏKİLDƏ yüksəkdir və `outranks()`
    qaydanı özü tətbiq edir; hardlock isə İKİNCİ, müstəqil qatdır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `EXECUTIVE` ADI SAXLANILIR (yeni üzvün adı `ROOT`-dur)
    ──────────────────────────────────────────────────────────────────────────
    `EXECUTIVE`-in MƏNASI dəyişmir — o, "şirkət rəhbərliyi" pilləsidir və
    dəyəri 0-dan 1-ə sürüşür. Alternativ (`EXECUTIVE`-i Root üçün saxlayıb CEO
    üçün yeni ad yaratmaq) RƏDD EDİLDİ: onda mövcud 100-dən çox istinadın hər
    biri sükutla MƏNA dəyişərdi (`RolePriority.EXECUTIVE` yazan hər sətir
    "CEO" əvəzinə "Root" oxunardı) və kompilyator bunu tutmazdı. İndiki
    seçimdə isə hər istinad ya olduğu kimi doğru qalır (CEO nəzərdə tutulurdu),
    ya da açıq şəkildə `RolePriority.ROOT`-a köçürülür.

    ──────────────────────────────────────────────────────────────────────────
    DB YARISI EYNİ DİAPAZONDADIR (miqrasiya 049)
    ──────────────────────────────────────────────────────────────────────────
    `positions.priority` CHECK-i əvvəl 0..9 idi, yəni DB `RolePriority`-nin
    tanımadığı bir dəyəri (məs. 7) QANUNİ sayırdı; `mappers.position_from_row`
    isə həmin sətirdə `RolePriority(7)` çağırıb `ValueError` atırdı. Boşluq
    sükutlu idi: ekranı yan keçən birbaşa `INSERT` bazada qalır, tətbiqdə isə
    "rol siyahısı açılmır" kimi görünürdü. 049 CHECK-i 0..4-ə daraltdı.

    ONA GÖRƏ: `Satıcı`-dan aşağı YENİ pillə əlavə edilərsə, dəyişiklik İKİ
    yerdədir (CLAUDE.md §5) — bu enum VƏ `positions.priority` CHECK-i
    (`schema.sql` §5 + yeni miqrasiya). Yalnız birini genişləndirmək köhnə
    qüsuru geri gətirər.
    """

    ROOT = 0  # Root — tenant-ın sistem sahibi, TƏK BAŞINA bu pillədə
    EXECUTIVE = 1  # CEO — şirkət rəhbəri, Root-dan DƏRHAL aşağı
    ADMIN = 2  # Admin
    OPERATIONAL = 3  # HR_Admin, Mağaza_Meneceri, Kamera_Nəzarətçisi
    STAFF = 4  # Satıcı və digər personel

    def outranks(self, other: RolePriority) -> bool:
        """`self` `other`-dan CİDDİ ŞƏKİLDƏ yüksəkdirmi.

        Strict Hierarchy Guard-ın əsası: bərabər pillə `False` qaytarır.
        """
        return self.value < other.value


class SystemRole(str, Enum):
    """7 defolt sistem rolu (spesifikasiya bölmə 3)."""

    ROOT = "ROOT"
    CEO = "CEO"
    ADMIN = "ADMIN"
    HR_ADMIN = "HR_ADMIN"
    STORE_MANAGER = "MAGAZA_MENECERI"
    CAMERA_OPERATOR = "KAMERA_NEZARETCISI"
    SELLER = "SATICI"

    @property
    def default_priority(self) -> RolePriority:
        return _DEFAULT_PRIORITIES[self]

    @property
    def is_camera_type(self) -> bool:
        """Kamera-əməliyyat flag-lərini daşıya bilən rol."""
        return self is SystemRole.CAMERA_OPERATOR


_DEFAULT_PRIORITIES: Final[dict[SystemRole, RolePriority]] = {
    # `Root` və `CEO` AYRI pillələrdir — bax `RolePriority` docstring-i.
    SystemRole.ROOT: RolePriority.ROOT,
    SystemRole.CEO: RolePriority.EXECUTIVE,
    SystemRole.ADMIN: RolePriority.ADMIN,
    SystemRole.HR_ADMIN: RolePriority.OPERATIONAL,
    SystemRole.STORE_MANAGER: RolePriority.OPERATIONAL,
    SystemRole.CAMERA_OPERATOR: RolePriority.OPERATIONAL,
    SystemRole.SELLER: RolePriority.STAFF,
}

#: Anti-fraud flag-lərinin HEÇ VAXT verilə bilməyəcəyi rollar (bölmə 3).
ANTI_FRAUD_FORBIDDEN_ROLES: Final[frozenset[SystemRole]] = frozenset(
    {SystemRole.STORE_MANAGER, SystemRole.SELLER}
)


# --------------------------------------------------------------------------- #
# Hardlock
# --------------------------------------------------------------------------- #


class HardlockLevel(IntEnum):
    """Dörd-səviyyəli hardlock iyerarxiyası (spesifikasiya bölmə 3).

    NONE:      adi operativ flag — rol-defolt + fərdi override.
    ROOT_ONLY: yalnız `Root` — `CEO`-ya belə verilmir.
    ROOT_CEO:  `Root` VƏ `CEO`.
    DELEGABLE: Root/CEO tərəfindən `Admin`-ə həvalə edilə bilər
               (Hierarchy + Self-Escalation Guard-a tabe).

    HARDLOCK PRİORİTET AYRILIĞINDAN SONRA DA DƏYİŞMİR: `ROOT_CEO` "Root VƏ
    CEO" deməkdir və `Root` (0) ilə `CEO` (1) artıq ayrı pillələrdə olsa da,
    bu səviyyə HƏR İKİSİNƏ icazə verir — hardlock "kimə verilə bilər"
    sualına cavabdır, "kim kimə toxuna bilər" sualına yox. İkinci sual
    Strict Hierarchy Guard-ındır və iki qat QƏSDƏN müstəqildir.
    """

    NONE = 0
    ROOT_ONLY = 1
    ROOT_CEO = 2
    DELEGABLE = 3

    def allows(self, role: SystemRole) -> bool:
        """Bu hardlock səviyyəsi verilmiş rola icazə verirmi."""
        if self is HardlockLevel.NONE:
            return True
        if self is HardlockLevel.ROOT_ONLY:
            return role is SystemRole.ROOT
        if self is HardlockLevel.ROOT_CEO:
            return role in (SystemRole.ROOT, SystemRole.CEO)
        # DELEGABLE — `Admin` pilləsi VƏ ondan yuxarı (Root, CEO, Admin).
        # Müqayisə ƏDƏDLƏ deyil, SİMVOLLA aparılır: prioritet dəyərləri
        # sürüşdükdə (Root/CEO ayrılığı) bu sətir olduğu kimi doğru qalır.
        # DB qarşılığı `enforce_permission_hardlock()`-dadır və orada ədəd
        # yazılmalıdır — məhz ona görə miqrasiya 048 həmin şərti də yeniləyir.
        return role.default_priority <= RolePriority.ADMIN


class PermissionEffect(str, Enum):
    """Fərdi override effekti — rol-defoltdan ÜSTÜNDÜR."""

    GRANT = "GRANT"
    DENY = "DENY"


# --------------------------------------------------------------------------- #
# Flag
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PermissionFlag:
    """Bir icazə flag-inin tam tərifi (`permission_flags` cədvəlinin əksi).

    Attributes:
        code: `can_issue_fines` kimi maşın-oxunaqlı açar.
        category: Admin panelində qruplaşdırma üçün.
        hardlock: Kimə verilə biləcəyini məhdudlaşdırır.
        is_anti_fraud: `Mağaza_Meneceri`/`Satıcı`-ya HEÇ VAXT verilmir.
        is_camera_only: ƏLAVƏ OLARAQ yalnız kamera-tipli rollarda ola bilər.
        excludes_camera_role: `is_camera_only`-nin ƏKSİ — kamera-tipli rola
            HEÇ VAXT verilmir. `can_publish_fines` üçün lazımdır: cəriməni
            YARADAN (`can_issue_fines`, kamera-xüsusi) ilə onu TƏSDİQ EDƏN
            eyni şəxs ola bilməz. "Defolt verilmir" kifayət deyildi —
            fərdi override ilə səhvən verilə bilərdi.
    """

    code: str
    category: str
    hardlock: HardlockLevel = HardlockLevel.NONE
    is_anti_fraud: bool = False
    is_camera_only: bool = False
    excludes_camera_role: bool = False

    def __post_init__(self) -> None:
        if not self.code or not self.code.startswith("can_"):
            raise ValueError(f"Flag kodu 'can_' ilə başlamalıdır: {self.code!r}")
        if self.is_camera_only and not self.is_anti_fraud:
            raise ValueError(
                f"{self.code}: `is_camera_only` yalnız anti-fraud flag-lərdə mənalıdır (SEC-001)"
            )
        if self.excludes_camera_role and not self.is_anti_fraud:
            raise ValueError(
                f"{self.code}: `excludes_camera_role` yalnız anti-fraud flag-lərdə mənalıdır"
            )
        if self.is_camera_only and self.excludes_camera_role:
            # Bu kombinasiya flag-i HEÇ BİR rola verilə bilməz edərdi —
            # yəni sükutla ölü flag yaradardı.
            raise ValueError(
                f"{self.code}: `is_camera_only` və `excludes_camera_role` "
                f"eyni anda ola bilməz — flag heç bir rola verilə bilməzdi"
            )

    # --------------------------- qoruyucu qaydalar -------------------------- #

    def assert_grantable_to(self, role: SystemRole, *, is_camera_type_role: bool = False) -> None:
        """Flag-in bu rola verilə biləcəyini yoxlayır, əks halda istisna atır.

        Args:
            role: Hədəf rol (custom rol üçün ən yaxın sistem rolu semantikası).
            is_camera_type_role: Custom rol açıq şəkildə "kamera-tipli"
                işarələnibsə `True`.
        """
        camera_capable = is_camera_type_role or role.is_camera_type

        if self.is_anti_fraud and role in ANTI_FRAUD_FORBIDDEN_ROLES:
            raise AuthorizationError(
                f"ANTI-FRAUD: '{self.code}' flag-i '{role.value}' rolunda ola bilməz "
                f"— vəzifə ayrılığı (bölmə 3)",
                context={"flag": self.code, "role": role.value},
            )

        if self.excludes_camera_role and camera_capable:
            raise AuthorizationError(
                f"VƏZİFƏ AYRILIĞI: '{self.code}' flag-i kamera-tipli rola "
                f"('{role.value}') verilə bilməz — cərimə YARADAN ilə cərimə "
                f"TƏSDİQ EDƏN eyni şəxs ola bilməz (bölmə 3)",
                context={"flag": self.code, "role": role.value},
            )

        if self.is_camera_only and not camera_capable:
            raise AuthorizationError(
                f"ANTI-FRAUD: '{self.code}' yalnız kamera-tipli rollarda ola bilər",
                context={"flag": self.code, "role": role.value},
            )

        # SEC-001: override YARADAN rol onu TƏSDİQLƏYƏ bilməz.
        if self.code == DUAL_CONTROL_APPROVAL_FLAG and camera_capable:
            raise AuthorizationError(
                "VƏZİFƏ AYRILIĞI: kamera-tipli rol dual-control təsdiqini daşıya "
                "bilməz — operator öz override-ını özü təsdiqləyərdi (SEC-001)",
                context={"flag": self.code, "role": role.value},
            )

        if not self.hardlock.allows(role):
            raise AuthorizationError(
                f"HARDLOCK (səviyyə {self.hardlock.value}): '{self.code}' flag-i "
                f"'{role.value}' rolunda ola bilməz",
                context={"flag": self.code, "role": role.value},
            )

    def is_grantable_to(self, role: SystemRole, *, is_camera_type_role: bool = False) -> bool:
        """İstisna atmayan variant — UI-da elementi gizlətmək üçün."""
        try:
            self.assert_grantable_to(role, is_camera_type_role=is_camera_type_role)
        except AuthorizationError:
            return False
        return True


DUAL_CONTROL_APPROVAL_FLAG: Final[str] = "can_approve_dual_control_override"


__all__ = [
    "ANTI_FRAUD_FORBIDDEN_ROLES",
    "DUAL_CONTROL_APPROVAL_FLAG",
    "AuthorizationError",
    "HardlockLevel",
    "PermissionEffect",
    "PermissionFlag",
    "RolePriority",
    "SystemRole",
]
