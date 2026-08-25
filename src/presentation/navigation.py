"""NavigationRegistry — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bölmə 3) — Faza 2.8.

QAYDA (spesifikasiyadan):
    "Tətbiq bir menyu içində HƏR ŞEYİ göstərib icazəsi olmayan bölmələri
    sadəcə «boz/deaktiv» etmə üsulu ilə QURULMAMALIDIR. … İstifadəçinin həmin
    flag-i yoxdursa, element UI-dan TAMAMİLƏ SİLİNİR (render olunmur)."

İKİ ŞƏRT EYNİ VAXTDA yoxlanılır:
    1. istifadəçinin icazəsi VAR, VƏ
    2. modul ROOT İdarə Mərkəzində AKTİVDİR (Feature Toggle).

Bu modul `presentation` qatındadır, lakin **PySide6-dan asılı DEYİL** —
yalnız saf məlumat strukturu və filtrləmə məntiqi. Faza 4-dəki Shell bu
reyestri oxuyub widget-ləri qurur; beləliklə naviqasiya qaydaları GUI olmadan
test oluna bilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from src.domain.entities.employee import Employee
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from collections.abc import Callable


class NavigationConfigError(KompasOSError):
    """Naviqasiya reyestri yanlış konfiqurasiya edilib."""

    user_message = "İnterfeys konfiqurasiyası xətası."


@dataclass(frozen=True)
class MenuEntry:
    """Bir menyu maddəsi / panel / widget.

    Attributes:
        key: Unikal açar (`leave_verification`, `permission_matrix`, ...).
        title_az: İstifadəçiyə görünən ad — YALNIZ Azərbaycan dilində (bölmə 9).
        required_flag: Görünmək üçün lazım olan icazə flag-i.
            `None` → hər autentifikasiya olunmuş istifadəçi görür (məs. "Ayarlar").
        required_flags: ƏLAVƏ flag-lər — HAMISI tələb olunur. Defolt boşdur,
            yəni mövcud 40+ maddənin heç birinin davranışı dəyişmir.
        feature_module: Bağlı olduğu Feature Toggle. `None` → toggle-dan asılı deyil.
        order: Menyuda sıra (kiçik əvvəl).
        parent_key: Alt-menyu üçün valideyn açarı.
        icon: İkon adı (Faza 4-də dizayn sistemi ilə uyğunlaşdırılır).

    ──────────────────────────────────────────────────────────────────────────
    `required_flags` NİYƏ ƏLAVƏ OLUNDU, `required_flag` NİYƏ QALDI
    ──────────────────────────────────────────────────────────────────────────
    Plugin manifesti bir DƏST flag elan edir (`PluginManifest.required_flags`)
    və plugin səhifəsi onların HAMISINI tələb etməlidir — birini seçib
    qalanını atmaq səlahiyyət qapısını sükutla zəiflədərdi (audit G-3).
    Mövcud sahəni dəstə çevirmək isə `menu.py`-dakı bütün maddələri,
    `test_menu_registry.py`-nin parametrləşdirilmiş yoxlamasını və `AdminShell`
    çağırışlarını toxundurardı. Ona görə köhnə sahə TOXUNULMADI, yenisi
    ONUN ÜSTÜNƏ QOYULDU: `required_flag` "əsas qapı", `required_flags` isə
    "əlavə qapılar"dır və ikisi VƏ ilə birləşir.
    """

    key: str
    title_az: str
    required_flag: str | None = None
    required_flags: frozenset[str] = field(default_factory=frozenset)
    feature_module: str | None = None
    order: int = 100
    parent_key: str | None = None
    icon: str | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise NavigationConfigError("Menyu açarı boş ola bilməz")
        if not self.title_az.strip():
            raise NavigationConfigError(f"'{self.key}' üçün başlıq boş ola bilməz")


@dataclass
class NavigationRegistry:
    """Modulların menyu maddələrini qeydiyyatdan keçirdiyi mərkəzi reyestr.

    Hər modul öz maddəsini ÖZÜ qeydiyyatdan keçirir — Shell modulları
    tanımır. Bu, yeni modul əlavə edərkən Shell-i dəyişməyə ehtiyacı aradan
    qaldırır və "menyuya əlavə etməyi unutdum" səhvini bağlayır.
    """

    _entries: dict[str, MenuEntry] = field(default_factory=dict)

    def register(self, entry: MenuEntry) -> None:
        if entry.key in self._entries:
            raise NavigationConfigError(
                f"Menyu açarı təkrarlanır: '{entry.key}'",
                context={"key": entry.key},
            )
        self._entries[entry.key] = entry

    def register_all(self, entries: list[MenuEntry]) -> None:
        for entry in entries:
            self.register(entry)

    def get(self, key: str) -> MenuEntry | None:
        return self._entries.get(key)

    @property
    def all_entries(self) -> tuple[MenuEntry, ...]:
        return tuple(sorted(self._entries.values(), key=lambda e: (e.order, e.key)))

    # ------------------------------ filtrləmə ------------------------------- #

    def visible_for(
        self,
        employee: Employee,
        *,
        now: datetime,
        enabled_modules: frozenset[str] | None = None,
        alternate_admission: Callable[[MenuEntry], bool] | None = None,
    ) -> tuple[MenuEntry, ...]:
        """İstifadəçinin GÖRDÜYÜ maddələr — qalanları ümumiyyətlə qaytarılmır.

        Args:
            enabled_modules: Aktiv Feature Toggle-ların açarları. `None`
                verildikdə bütün modullar aktiv sayılır (test rahatlığı üçün).
            alternate_admission: ƏLAVƏ QƏBUL — flag yoxlaması ALINMAYANDA
                çağırılan son şans (`v2backlog.md` Faza 5.4). Bax `is_visible`
                başlığındakı tam əsaslandırma; burada YALNIZ imza qaydası:
                callable MADDƏNİ qaytarmalıdır, istisna atmamalıdır — menyu
                quruluşu bir pis callable-ın əsiri olmamalıdır.

        Returns:
            Sıralanmış maddələr. Valideyni görünməyən alt-maddə də gizlədilir.
        """
        visible: dict[str, MenuEntry] = {}

        for entry in self.all_entries:
            if not self._is_visible(
                entry,
                employee,
                now=now,
                modules=enabled_modules,
                alternate_admission=alternate_admission,
            ):
                continue
            visible[entry.key] = entry

        # Valideyni görünməyən alt-maddələr "asılı qalmamalıdır".
        return tuple(
            entry
            for entry in visible.values()
            if entry.parent_key is None or entry.parent_key in visible
        )

    def is_visible(
        self,
        key: str,
        employee: Employee,
        *,
        now: datetime,
        enabled_modules: frozenset[str] | None = None,
        alternate_admission: Callable[[MenuEntry], bool] | None = None,
    ) -> bool:
        """Tək maddə üçün yoxlama — ekrana birbaşa keçid (deep link) qoruması.

        VACİB: menyunun gizlədilməsi TƏHLÜKƏSİZLİK DEYİL. Ekranı açan hər
        əməliyyat öz icazəsini AYRICA yoxlamalıdır — bu metod həmin yoxlama
        üçün də istifadə olunur.

        ──────────────────────────────────────────────────────────────────────
        `alternate_admission` NİYƏ VAR — «Fövqəladə Giriş» (Faza 5.4)
        ──────────────────────────────────────────────────────────────────────
        Ehtiyat-admin (break-glass trustee) HEÇ BİR icazə flag-i daşımır — onun
        səlahiyyəti REYESTR SƏTRİDİR (`break_glass_trustees`), flag deyil. Flag
        yoxlaması ilə qapılan maddə təyin edilmiş ehtiyat-admini ekrana
        buraxmırdı, mexanizm isə məhz o, daxil olanda lazımdır. Ona görə örtük
        (AdminShell) login-də BİR dəfə reyestr oxuyub bu callable ilə «bu
        işçi ehtiyat-admindir» faktını menyuya ÖTÜRÜR.

        QAYDALAR QORUNUR:
        * Feature Toggle yoxlaması (Şərt 1) callable ilə YAN KEÇİLMİR — söndürülmüş
          modul heç vaxt görünmür;
        * `required_flags` (hamısı-VƏ) yoxlaması da yan keçilmir;
        * Bu, GÖRÜNÜRLÜKDÜR, İCAZƏ DEYİL: ekranı açan hər əməliyyat use case-in
          öz qapısına düşür (`request_access`/`approve`/`revoke`) — callable
          heç bir yazı yoluna çata bilmir.
        """
        entry = self._entries.get(key)
        if entry is None:
            return False
        if not self._is_visible(
            entry,
            employee,
            now=now,
            modules=enabled_modules,
            alternate_admission=alternate_admission,
        ):
            return False
        if entry.parent_key is not None:
            return self.is_visible(
                entry.parent_key,
                employee,
                now=now,
                enabled_modules=enabled_modules,
                alternate_admission=alternate_admission,
            )
        return True

    @staticmethod
    def _is_visible(
        entry: MenuEntry,
        employee: Employee,
        *,
        now: datetime,
        modules: frozenset[str] | None,
        alternate_admission: Callable[[MenuEntry], bool] | None = None,
    ) -> bool:
        # Şərt 1 — modul aktivdirmi (ROOT İdarə Mərkəzi)
        if (
            entry.feature_module is not None
            and modules is not None
            and entry.feature_module not in modules
        ):
            return False
        # Şərt 2 — istifadəçinin icazəsi varmı
        #
        # `required_flags` (əlavə qapılar) `required_flag`-dən ASILI OLMADAN
        # yoxlanılır: plugin səhifəsi bir neçə flag tələb edə bilər və birinin
        # olmaması maddəni gizlətməlidir (bax `MenuEntry` başlığı, audit G-3).
        if any(not employee.has_permission(flag, now=now) for flag in entry.required_flags):
            return False
        if entry.required_flag is None:
            return True
        if employee.has_permission(entry.required_flag, now=now):
            return True
        # Şərt 3 — zəng edənin əlavə qəbulu. Yalnız flag ALINMADIQDA çatır və
        # modul toggle-ını heç vaxt yan keçə bilmir (o, yuxarıda rədd edib).
        return alternate_admission is not None and alternate_admission(entry)

    def clear(self) -> None:
        """Reyestri sıfırlayır — əsasən testlər üçün."""
        self._entries.clear()


__all__ = ["MenuEntry", "NavigationConfigError", "NavigationRegistry"]
