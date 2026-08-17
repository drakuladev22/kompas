"""Cihaz qeydiyyatı — hansı PC hansı filiala aiddir (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ IP ÜNVANI DEYİL
──────────────────────────────────────────────────────────────────────────────
Filialı IP ilə tanımaq ilk baxışda pulsuz görünür, lakin üç yerdə sınır:
dinamik IP dəyişir, bir neçə filial eyni NAT/public IP arxasında ola bilər,
VPN/provayder dəyişəndə bağlantı itir. Hər üç halda nəticə EYNİDİR: cərimə,
tabel və kamera scoping-i SƏHV filiala yazılır — və qüsur sükutludur, çünki
sistem özünü tam işlək hesab edir.

Əvəzinə cihaz ÖZÜNÜ tanıdır: ilk açılışda `device_id` yaradır, admin onu
konkret filiala TƏYİN edir. Təyin edilməmiş cihaz İŞLƏMİR — «bilmirəm, ona
görə hər yerə yazıram» variantı yoxdur.

──────────────────────────────────────────────────────────────────────────────
`hardware_fingerprint` KİMLİK DEYİL — DƏYİŞİKLİK DETEKTORUDUR
──────────────────────────────────────────────────────────────────────────────
Kimlik `device_id` UUID-idir və `%PROGRAMDATA%`-dakı konfiqurasiyada yaşayır.
Fingerprint (anakart/disk seriyası + Windows machine GUID hash-i) ONA ƏLAVƏ
ölçüdür.

Fingerprint-i kimliyin ÖZÜ saysaydıq, disk dəyişdirmək — yəni adi təmir —
cihazın özünü itirməsi demək olardı: mağaza səhər açılanda «bu cihaz
təsdiqlənməyib» görərdi. Əksinə, fingerprint-i tamamilə nəzərə almasaydıq,
`device_id`-ni bir konfiqurasiya faylından digərinə köçürməklə təsdiqlənmiş
cihazın kimliyini oğurlamaq mümkün olardı.

Ona görə orta yol seçilib: uyğunsuzluq BLOKLAMIR, lakin audit-ə yazılır və
admin ekranında görünür. Qərarı adam verir, çünki «disk dəyişdirildi» ilə
«fayl köçürüldü» arasındakı fərqi yalnız adam bilir.

──────────────────────────────────────────────────────────────────────────────
QISA KOD TELEFONLA SÖYLƏNİLİR
──────────────────────────────────────────────────────────────────────────────
Gözləmə ekranındakı kod tam UUID DEYİL. Səbəb praktikdir: mağaza işçisi onu
telefonla admin-ə deyir və 36 simvollu UUID bu iş üçün yararsızdır. Əlifbadan
qarışan simvollar (0/O, 1/I/L, 5/S, 2/Z) ÇIXARILIB — səhv eşidilən bir simvol
admini başqa cihazı təsdiqləməyə apara bilərdi.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Final

#: Qısa kodun əlifbası — qarışan simvollar YOXDUR (bax modul başlığı).
#: Crockford Base32-nin məhdudlaşdırılmış variantıdır.
SHORT_CODE_ALPHABET: Final[str] = "34679ACDEFGHJKMNPQRTUVWXY"

#: Qısa kodun uzunluğu. 6 simvol × 25 əlifba = ~244 milyon kombinasiya —
#: bir kirayəçinin cihaz sayı (onlarla) yanında toqquşma ehtimalı sıfıra
#: yaxındır, telefonla söyləmək isə hələ asandır.
#:
#: NİYƏ ROOT PARAMETRİ DEYİL: kod insan ergonomikasının ölçüsüdür, biznes
#: siyasəti deyil. Root onu 3-ə endirsəydi toqquşma real olardı, 20-yə
#: qaldırsaydı kodun bütün mənası (telefonla söylənilməsi) itərdi.
SHORT_CODE_LENGTH: Final[int] = 6

#: Fingerprint hash-inin uzunluğu (hex simvol). Tam SHA-256 saxlanılmır:
#: 64 simvol ekranda oxunmur və müqayisə üçün 32 kifayət edir (2^128 sahə).
FINGERPRINT_HASH_LENGTH: Final[int] = 32


class DeviceType(str, Enum):
    """Cihazın rolu — hansı ekranların açılacağını müəyyən edir.

    `str, Enum` qəsdəndir (`CLAUDE.md` §4): dəyər DB sütununa və audit
    sətrinə olduğu kimi düşür.
    """

    #: Mağazadakı toxunma ekranı — işçi giriş/çıxışı.
    KIOSK = "KIOSK"
    #: Ofis/mağaza idarə kompüteri — admin panelləri.
    ADMIN_PC = "ADMIN_PC"
    #: Kamera operatorunun iş yeri — təsdiq növbəsi.
    CAMERA_OPERATOR = "CAMERA_OPERATOR"


class DeviceStatus(str, Enum):
    """Cihazın qeydiyyat vəziyyəti."""

    #: Qeydiyyat yaradılıb, admin təsdiqi GÖZLƏNİLİR. Tətbiq İŞLƏMİR.
    PENDING_APPROVAL = "PENDING_APPROVAL"
    #: Təsdiqlənib və filiala təyin edilib. Tətbiq işləyir.
    ACTIVE = "ACTIVE"
    #: Admin bloklayıb və ya passivlik həddi keçib. Tətbiq İŞLƏMİR.
    BLOCKED = "BLOCKED"

    @property
    def allows_operation(self) -> bool:
        """Bu vəziyyətdə tətbiq işləyə bilərmi.

        Xassə kimi yazılıb ki, «hansı statuslar işləyir» sualı TƏK yerdə
        cavablansın: yeni status əlavə olunanda onu unudulmuş bir `if`-də
        sükutla «işləyir» saymaq mümkün olmasın.
        """
        return self is DeviceStatus.ACTIVE


@dataclass(frozen=True)
class DeviceFingerprint:
    """Aparat kimliyinin hash-i — XAM seriya nömrələri SAXLANILMIR.

    Xam dəyər (anakart seriyası, disk seriyası, machine GUID) saxlansaydı,
    baza sızması müştərinin bütün avadanlıq inventarını verərdi. Hash isə
    müqayisə üçün kifayətdir: bizə lazım olan «dəyişdimi» sualıdır, «nədir»
    sualı deyil.
    """

    value: str

    def __post_init__(self) -> None:
        if len(self.value) != FINGERPRINT_HASH_LENGTH:
            raise ValueError(
                f"Fingerprint hash-i {FINGERPRINT_HASH_LENGTH} simvol olmalıdır, "
                f"faktiki {len(self.value)}"
            )

    @classmethod
    def from_parts(cls, *parts: str) -> DeviceFingerprint:
        """Aparat göstəricilərindən hash qurur.

        Hissələr `|` ilə birləşdirilir və HƏR BİRİ ayrıca normallaşdırılır
        (kənar boşluqlar, böyük hərf). Normallaşdırma olmasaydı, eyni maşın
        WMI-nin qaytardığı formatdan asılı olaraq iki fərqli fingerprint
        verə bilərdi və hər Windows yeniləməsindən sonra «cihaz dəyişdi»
        xəbərdarlığı çıxardı.

        Boş hissələr ATILIR: bəzi maşınlarda WMI seriya nömrəsini boş
        qaytarır və boş sətri hash-ə qatmaq həmin maşınları bir-birinə
        yaxınlaşdırardı, uzaqlaşdırmazdı.
        """
        cleaned = [part.strip().upper() for part in parts if part and part.strip()]
        if not cleaned:
            raise ValueError("Fingerprint üçün heç bir aparat göstəricisi verilmədi")
        digest = hashlib.sha256("|".join(cleaned).encode("utf-8")).hexdigest()
        return cls(digest[:FINGERPRINT_HASH_LENGTH])


def generate_short_code(*, randomizer: secrets.SystemRandom | None = None) -> str:
    """Telefonla söylənilə bilən qeydiyyat kodu yaradır.

    `secrets` işlədilir, `random` YOX: kod təsdiq axınının bir hissəsidir və
    təxmin edilə bilən ardıcıllıq admini başqasının cihazını təsdiqləməyə
    yönləndirməyə imkan verərdi. Qiyməti sıfırdır — kod cihaz ömrü boyu bir
    dəfə yaranır.
    """
    rng = randomizer or secrets.SystemRandom()
    return "".join(rng.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


def normalize_short_code(raw: str) -> str:
    """Admin-in yazdığı kodu müqayisəyə hazırlayır.

    Boşluq, defis və kiçik hərf ATILIR — admin kodu telefonla eşidib yazır və
    «A3-7K M9» formasında daxil etməsi normaldır. Əlifbada olmayan simvol
    QALIR (silmirik): onu sükutla atmaq «kod tapılmadı» xətasını izah edilməz
    edərdi, çünki admin ekranda yazdığı ilə axtarılan arasındakı fərqi
    görməzdi.
    """
    return "".join(ch for ch in raw.upper() if ch not in {" ", "-", "\t"})


@dataclass(frozen=True)
class DeviceRegistrationRequest:
    """İlk açılışda yaradılan qeydiyyat sorğusu.

    Bu, hələ CİHAZ deyil — cihaz olmaq üçün admin təsdiqi lazımdır. Ayrı tip
    olması qəsdəndir: `store_id` burada YOXDUR və olmamalıdır, çünki filialı
    cihaz özü SEÇMİR (seçsəydi, IP yanaşmasının eyni qüsuru — özünü səhv
    yerə yazan cihaz — geri qayıdardı).
    """

    device_id: str
    fingerprint: DeviceFingerprint
    short_code: str
    #: Maşının şəbəkə adı — admin cihazı tanıya bilsin deyə (ad TƏKLİFİdir,
    #: kimlik deyil; admin onu dəyişə bilər).
    machine_name: str
    device_type: DeviceType


__all__ = [
    "FINGERPRINT_HASH_LENGTH",
    "SHORT_CODE_ALPHABET",
    "SHORT_CODE_LENGTH",
    "DeviceFingerprint",
    "DeviceRegistrationRequest",
    "DeviceStatus",
    "DeviceType",
    "generate_short_code",
    "normalize_short_code",
]
