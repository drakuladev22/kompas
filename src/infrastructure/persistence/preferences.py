"""İstifadəçi tərcihləri — tema, dil, dashboard düzülüşü (bölmə 9, 6) — Faza 4/6.

    "İstifadəçi istənilən vaxt Ayarlar menyusundan keçid edə bilər; seçim
     `user_preferences` cədvəlində saxlanılır və NÖVBƏTİ LOGIN-də tətbiq
     olunur." (bölmə 9)

Son cümlə bu modulun mövcudluq səbəbidir: tema seçimi yalnız yaddaşda
saxlansaydı, tətbiq bağlananda itərdi və istifadəçi hər gün onu yenidən
seçməli olardı.

──────────────────────────────────────────────────────────────────────────────
`SYSTEM` NİYƏ SAXLANILIR
──────────────────────────────────────────────────────────────────────────────
Üç dəyər var: `LIGHT`, `DARK`, `SYSTEM`. Üçüncüsü "seçim yoxdur" DEYİL —
açıq şəkildə "OS-in seçiminə uyğunlaş" deməkdir. Onu `NULL` kimi saxlasaydıq,
"heç vaxt seçməyib" ilə "sistemə uyğun seçib" halları eyni görünərdi və
defolt dəyişdikdə istifadəçinin qəsdli seçimi sükutla itərdi.

──────────────────────────────────────────────────────────────────────────────
DİL NİYƏ SAXLANILIR, AMMA SEÇİLMİR
──────────────────────────────────────────────────────────────────────────────
Sütun `CHECK (language IN ('az'))` ilə məhduddur və Ayarlar ekranında dil
seçimi GÖSTƏRİLMİR (bölmə 9: "yalnız bir dil var"). Sütun i18n arxitekturası
üçün saxlanılır — burada yalnız oxunur ki, gələcəkdə ikinci dil əlavə
olunanda kod dəyişikliyi tələb olunmasın.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId

_log = get_logger(__name__)

#: `theme_preference` enum-unun icazə verdiyi dəyərlər.
VALID_THEMES: Final[frozenset[str]] = frozenset({"LIGHT", "DARK", "SYSTEM"})
DEFAULT_THEME: Final[str] = "SYSTEM"
DEFAULT_LANGUAGE: Final[str] = "az"


class PostgresUserPreferences(_BaseRepository):
    """`user_preferences` — tema, dil və dashboard düzülüşü."""

    def theme_for(self, employee_id: EmployeeId) -> str:
        """Saxlanmış tema; sətir yoxdursa `SYSTEM`.

        Sətrin olmaması NORMAL haldır: istifadəçi Ayarlar ekranını heç vaxt
        açmaya bilər. `INSERT` yalnız faktiki seçim edildikdə baş verir —
        hər login-də boş sətir yaratmaq cədvəli mənasız doldurardı.
        """
        row = self._fetch_one(
            "SELECT theme FROM user_preferences WHERE user_id = %s",
            (employee_id,),
        )
        if row is None:
            return DEFAULT_THEME
        theme = str(row["theme"])
        if theme not in VALID_THEMES:
            _log.warning(
                "UNKNOWN_THEME_PREFERENCE",
                extra={"employee_id": str(employee_id), "theme": theme},
            )
            return DEFAULT_THEME
        return theme

    def set_theme(self, employee_id: EmployeeId, theme: str) -> None:
        """Ayarlar ekranındakı seçimi yazır."""
        normalized = theme.strip().upper()
        if normalized not in VALID_THEMES:
            raise ValueError(f"Naməlum tema dəyəri: {theme!r}")

        self._execute(
            """
            INSERT INTO user_preferences (user_id, theme)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET theme = EXCLUDED.theme
            """,
            (employee_id, normalized),
        )

    def notification_prefs(self, employee_id: EmployeeId) -> dict[str, bool]:
        """Bildiriş kanallarının vəziyyəti (miqrasiya 058).

        AÇAR YOXDURSA KANAL AÇIQ SAYILIR və bu, qərarın özüdür: sətri olmayan
        istifadəçi bugünkü davranışı görməlidir. Əks qayda (yoxdursa bağlıdır)
        miqrasiya anında hamının bildirişini sükutla kəsərdi.
        """
        row = self._fetch_one(
            "SELECT notification_prefs FROM user_preferences WHERE user_id = %s",
            (employee_id,),
        )
        if row is None or row["notification_prefs"] is None:
            return {}
        raw = row["notification_prefs"]
        if not isinstance(raw, dict):
            _log.warning(
                "UNREADABLE_NOTIFICATION_PREFERENCE",
                extra={"employee_id": str(employee_id)},
            )
            return {}
        return {str(key): bool(value) for key, value in raw.items()}

    def set_notification_prefs(self, employee_id: EmployeeId, prefs: dict[str, bool]) -> None:
        """Bildiriş açarlarını yazır — tema ilə EYNİ `ON CONFLICT` naxışı."""
        import json  # noqa: PLC0415

        self._execute(
            """
            INSERT INTO user_preferences (user_id, notification_prefs)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (user_id)
            DO UPDATE SET notification_prefs = EXCLUDED.notification_prefs
            """,
            (employee_id, json.dumps({key: bool(value) for key, value in prefs.items()})),
        )

    def language_for(self, employee_id: EmployeeId) -> str:
        row = self._fetch_one(
            "SELECT language FROM user_preferences WHERE user_id = %s",
            (employee_id,),
        )
        return str(row["language"]) if row else DEFAULT_LANGUAGE

    # --------------------------- kiosk bələdçisi ----------------------------- #

    def kiosk_onboarding_done(self, employee_id: EmployeeId) -> bool:
        """Kiosk bələdçisi bu istifadəçi üçün göstərilibmi (Faza 10).

        SƏTRİN OLMAMASI «görməyib» deməkdir — `theme_for` ilə EYNİ fail-safe:
        heç vaxt Ayarlar-a girməmiş kiosk işçisinin sətri olmur və ona görə
        bayraq `False` oxunur, xəta atılmır.
        """
        row = self._fetch_one(
            "SELECT kiosk_onboarding_done FROM user_preferences WHERE user_id = %s",
            (employee_id,),
        )
        if row is None or row["kiosk_onboarding_done"] is None:
            return False
        return bool(row["kiosk_onboarding_done"])

    def mark_kiosk_onboarding_done(self, employee_id: EmployeeId) -> None:
        """Bələdçini «görüldü» kimi yazır — «KEÇ» DƏ BURADAN KEÇİR.

        Qəsdən İKİTƏRƏFLİDİR: məqsəd məcburiyyət deyil, tanışlıqdır; «Keç»-ə
        basan işçinin qarşıda yenidən eyni overlay görməsi əks təsir verərdi.
        UPSERT digər tərcih sütunlarına TOXUNMUR (`ON CONFLICT DO UPDATE`
        yalnız bu sütunu dəyişir).
        """
        self._execute(
            """
            INSERT INTO user_preferences (user_id, kiosk_onboarding_done)
            VALUES (%s, TRUE)
            ON CONFLICT (user_id)
            DO UPDATE SET kiosk_onboarding_done = TRUE
            """,
            (employee_id,),
        )

    # -------------------------- dashboard düzülüşü --------------------------- #

    def load(self, employee_id: EmployeeId) -> list[str] | None:
        """`DashboardLayoutStore.load` — `None` = heç vaxt saxlanmayıb.

        BOŞ massiv (`[]`) ilə `None` FƏRQLİDİR (migration 011): birincisi
        "hər şeyi gizlətdim", ikincisi "heç nə qurmamışam" deməkdir.
        """
        row = self._fetch_one(
            "SELECT dashboard_layout FROM user_preferences WHERE user_id = %s",
            (employee_id,),
        )
        if row is None or row["dashboard_layout"] is None:
            return None
        return _as_key_list(row["dashboard_layout"])

    def save(self, employee_id: EmployeeId, layout: list[str]) -> None:
        """`DashboardLayoutStore.save` — düzülüş TAM əvəzlənir."""
        self._execute(
            """
            INSERT INTO user_preferences (user_id, dashboard_layout, dashboard_updated_at)
            VALUES (%s, %s::jsonb, now())
            ON CONFLICT (user_id) DO UPDATE
                SET dashboard_layout     = EXCLUDED.dashboard_layout,
                    dashboard_updated_at = now()
            """,
            (employee_id, json.dumps(list(layout))),
        )


def _as_key_list(raw: Any) -> list[str]:
    """`JSONB` sütununu sətir siyahısına çevirir.

    Sürücü `jsonb`-i artıq Python obyekti kimi qaytarır, lakin köhnə
    yazılarda sətir də ola bilər — hər iki hal emal olunur ki, bir dəfəlik
    format fərqi ekranı sındırmasın.
    """
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


__all__ = [
    "DEFAULT_LANGUAGE",
    "DEFAULT_THEME",
    "VALID_THEMES",
    "PostgresUserPreferences",
]
