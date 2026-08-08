"""NavigationRegistry — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" (bölmə 3) — Faza 2.8.

QAYDA (spesifikasiyadan):
    "Tətbiq bir menyu içində HƏR ŞEYİ göstərib icazəsi olmayan bölmələri
    sadəcə «boz/deaktiv» etmə üsulu ilə QURULMAMALIDIR. … İstifadəçinin həmin
    flag-i yoxdursa, element UI-dan TAMAMİLƏ SİLİNİR (render olunmur)."

İKİ ŞƏRT EYNİ VAXTDA yoxlanılır:
    1. istifadəçinin icazəsi VAR, VƏ
    2. modul Root Control Center-də AKTİVDİR (Feature Toggle).

Bu modul `presentation` qatındadır, lakin **PySide6-dan asılı DEYİL** —
yalnız saf məlumat strukturu və filtrləmə məntiqi. Faza 4-dəki Shell bu
reyestri oxuyub widget-ləri qurur; beləliklə naviqasiya qaydaları GUI olmadan
test oluna bilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.domain.entities.employee import Employee
from src.shared.exceptions import KompasOSError


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
        feature_module: Bağlı olduğu Feature Toggle. `None` → toggle-dan asılı deyil.
        order: Menyuda sıra (kiçik əvvəl).
        parent_key: Alt-menyu üçün valideyn açarı.
        icon: İkon adı (Faza 4-də dizayn sistemi ilə uyğunlaşdırılır).
    """

    key: str
    title_az: str
    required_flag: str | None = None
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
    ) -> tuple[MenuEntry, ...]:
        """İstifadəçinin GÖRDÜYÜ maddələr — qalanları ümumiyyətlə qaytarılmır.

        Args:
            enabled_modules: Aktiv Feature Toggle-ların açarları. `None`
                verildikdə bütün modullar aktiv sayılır (test rahatlığı üçün).

        Returns:
            Sıralanmış maddələr. Valideyni görünməyən alt-maddə də gizlədilir.
        """
        visible: dict[str, MenuEntry] = {}

        for entry in self.all_entries:
            if not self._is_visible(entry, employee, now=now, modules=enabled_modules):
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
    ) -> bool:
        """Tək maddə üçün yoxlama — ekrana birbaşa keçid (deep link) qoruması.

        VACİB: menyunun gizlədilməsi TƏHLÜKƏSİZLİK DEYİL. Ekranı açan hər
        əməliyyat öz icazəsini AYRICA yoxlamalıdır — bu metod həmin yoxlama
        üçün də istifadə olunur.
        """
        entry = self._entries.get(key)
        if entry is None:
            return False
        if not self._is_visible(entry, employee, now=now, modules=enabled_modules):
            return False
        if entry.parent_key is not None:
            return self.is_visible(
                entry.parent_key, employee, now=now, enabled_modules=enabled_modules
            )
        return True

    @staticmethod
    def _is_visible(
        entry: MenuEntry,
        employee: Employee,
        *,
        now: datetime,
        modules: frozenset[str] | None,
    ) -> bool:
        # Şərt 1 — modul aktivdirmi (Root Control Center)
        if (
            entry.feature_module is not None
            and modules is not None
            and entry.feature_module not in modules
        ):
            return False
        # Şərt 2 — istifadəçinin icazəsi varmı
        if entry.required_flag is None:
            return True
        return employee.has_permission(entry.required_flag, now=now)

    def clear(self) -> None:
        """Reyestri sıfırlayır — əsasən testlər üçün."""
        self._entries.clear()


__all__ = ["MenuEntry", "NavigationConfigError", "NavigationRegistry"]
