"""Konfiqurasiya və cədvəl repository-ləri — Faza 5.

`repositories.py` aqreqat repo-larını (Employee, Fine, …) saxlayır. Bu modul
isə ROOT İdarə Mərkəzi və növbə/icazə kataloqlarının arxasındakı SADƏ
oxu/yazma portlarını tamamlayır:

    SystemLimits                — konfiqurasiya edilə bilən limitlər
    FeatureToggles              — modul aç/bağla
    PermissionFlagRepository    — icazə registri
    LeaveTypeRepository         — icazə növləri
    ShiftRepository             — növbə planı (off-day, planlaşdırılmış başlanğıc)
    CameraAssignmentRepository  — operator → mağaza təyinatı

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL
──────────────────────────────────────────────────────────────────────────────
Bunlar AQREQAT DEYİL — domen obyektini bərpa etmirlər, sadəcə skalyar dəyər
və ya siyahı qaytarırlar. `repositories.py`-a əlavə etmək həmin faylı 1000+
sətrə çatdırar və iki fərqli məsuliyyəti (aqreqat bərpası ↔ konfiqurasiya
oxunuşu) qarışdırardı.

──────────────────────────────────────────────────────────────────────────────
`tenant_id` NİYƏ HƏR SORĞUDA VAR
──────────────────────────────────────────────────────────────────────────────
RLS (SEC-008) `SET LOCAL app.tenant_id` ilə işləyir, lakin sorğuda da açıq
şərt saxlanılır: RLS siyasəti bir gün səhv konfiqurasiya edilsə, sorğu yenə
də başqa tenant-ın sətrini qaytarmır. Müdafiə iki qatdadır (defense-in-depth).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from src.domain.entities.shift import ShiftAssignment, ShiftSource
from src.domain.policies import BreakKind, SystemLimitKey
from src.domain.value_objects.authorization import HardlockLevel, PermissionFlag
from src.domain.value_objects.catalogs import MAX_LEAVE_DURATION_MINUTES, LeaveType

# `TenantId` RUNTIME İDXALDIR, `TYPE_CHECKING` bloku DEYİL: `LeaveType._hydrate`
# onu ÇAĞIRIR (`TenantId(row["tenant_id"])`), yəni yalnız tip-yoxlaması üçün
# idxal edilsəydi kataloq bazadan oxunanda `NameError` atardı. Qüsur uzun müddət
# görünməz qaldı, çünki həmin yolu yalnız `DATABASE_URL` tələb edən inteqrasiya
# testləri gəzirdi — indi vahid test də onu gəzir (bax `test_config_repositories`).
from src.domain.value_objects.identifiers import TenantId
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from datetime import date

    from src.domain.value_objects.identifiers import (
        EmployeeId,
        LeaveTypeId,
        StoreId,
    )

_log = get_logger(__name__)

#: Struktur-kritik modul söndürülərkən yazılı təsdiq tələb olunur (bölmə 3).
STRUCTURAL_CONFIRMATION_REQUIRED: Final = "STRUKTUR-KRİTİK"


# --------------------------------------------------------------------------- #
# SystemLimits
# --------------------------------------------------------------------------- #


class PostgresSystemLimits(_BaseRepository):
    """ROOT İdarə Mərkəzi limitləri (`system_limits` cədvəli)."""

    def get_int(self, tenant_id: TenantId, key: str, default: int) -> int:
        """Tam ədəd limit.

        Dəyər yoxdursa və ya rəqəm deyilsə DEFAULT qaytarılır — konfiqurasiya
        səhvi bütün axını dayandırmamalıdır. Yararsız dəyər jurnal edilir ki,
        səssiz qalmasın.
        """
        raw = self._raw(tenant_id, key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            _log.warning(
                "SYSTEM_LIMIT_NOT_AN_INTEGER",
                extra={"limit_key": key, "raw_value": raw, "fallback": default},
            )
            return default

    def get_str(self, tenant_id: TenantId, key: str, default: str) -> str:
        raw = self._raw(tenant_id, key)
        return default if raw is None else raw

    def all_for(self, tenant_id: TenantId) -> dict[str, str]:
        rows = self._fetch_all(
            "SELECT limit_key, limit_value FROM system_limits WHERE tenant_id = %s",
            (tenant_id,),
        )
        return {row["limit_key"]: row["limit_value"] for row in rows}

    def describe(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        """ROOT ekranı üçün tam təsvir — min/max və izah daxil.

        `all_for()` yalnız dəyəri verir; ekranda isə slayder hüdudları və
        Azərbaycanca izah lazımdır.
        """
        return self._fetch_all(
            """
            SELECT limit_key, limit_value, value_type, min_value, max_value,
                   description_az, changed_at
            FROM system_limits
            WHERE tenant_id = %s
            ORDER BY limit_key
            """,
            (tenant_id,),
        )

    def set_value(
        self,
        tenant_id: TenantId,
        key: str,
        value: str,
        *,
        changed_by: EmployeeId,
    ) -> None:
        """Limiti yazır (UPSERT) və dəyişəni qeyd edir.

        `changed_by` MƏCBURİDİR: ROOT əməliyyatları audit jurnalına düşməlidir
        (bölmə 3) və "kim dəyişdi" sualı sonradan cavablandırıla bilməlidir.
        """
        self._execute(
            """
            INSERT INTO system_limits (tenant_id, limit_key, limit_value, changed_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, limit_key)
            DO UPDATE SET limit_value = EXCLUDED.limit_value,
                          changed_by  = EXCLUDED.changed_by,
                          changed_at  = now()
            """,
            (tenant_id, key, value, changed_by),
        )

    def _raw(self, tenant_id: TenantId, key: str) -> str | None:
        row = self._fetch_one(
            "SELECT limit_value FROM system_limits WHERE tenant_id = %s AND limit_key = %s",
            (tenant_id, key),
        )
        return row["limit_value"] if row else None


# --------------------------------------------------------------------------- #
# FeatureToggles
# --------------------------------------------------------------------------- #


class PostgresFeatureToggles(_BaseRepository):
    """Modul aç/bağla (`feature_toggles` cədvəli).

    RETROAKTİV TƏSİRSİZLİK: bu repo yalnız CARİ vəziyyəti verir. Söndürülmüş
    modulun MÖVCUD qeydləri toxunulmaz qalır — həmin qayda use case
    səviyyəsindədir, burada deyil.
    """

    def is_enabled(self, tenant_id: TenantId, module_key: str) -> bool:
        """Modul aktivdirmi.

        Sətir YOXDURSA `True` qaytarılır: yeni modul əlavə edildikdə hər
        tenant üçün sətir yaratmaq unudula bilər və o zaman modul səssizcə
        yox olardı. Söndürmək AÇIQ əməliyyat olmalıdır.
        """
        row = self._fetch_one(
            "SELECT is_enabled FROM feature_toggles WHERE tenant_id = %s AND module_key = %s",
            (tenant_id, module_key),
        )
        return True if row is None else bool(row["is_enabled"])

    def enabled_modules(self, tenant_id: TenantId) -> frozenset[str]:
        """Aktiv modulların açarları — naviqasiya süzgəci üçün."""
        rows = self._fetch_all(
            "SELECT module_key FROM feature_toggles WHERE tenant_id = %s AND is_enabled",
            (tenant_id,),
        )
        return frozenset(row["module_key"] for row in rows)

    def describe(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        """ROOT ekranı üçün — struktur-kritik bayrağı ilə birlikdə."""
        return self._fetch_all(
            """
            SELECT module_key, is_enabled, is_structural, description_az, changed_at
            FROM feature_toggles
            WHERE tenant_id = %s
            ORDER BY module_key
            """,
            (tenant_id,),
        )

    def set_enabled(
        self,
        tenant_id: TenantId,
        module_key: str,
        *,
        enabled: bool,
        changed_by: EmployeeId,
        confirmation: str | None = None,
    ) -> None:
        """Modulu açır/söndürür.

        Raises:
            ValueError: Struktur-kritik modul yazılı təsdiq olmadan söndürülür.

        Təsdiq mətni BURADA tələb olunur, ekranda deyil: modal-ı yan keçən
        hər hansı yol (skript, gələcək API) da eyni qaydaya tabe olmalıdır.
        """
        if not enabled and self.is_structural(tenant_id, module_key) and not confirmation:
            raise ValueError(
                f"'{module_key}' struktur-kritik moduldur — söndürmək üçün "
                "yazılı təsdiq tələb olunur"
            )

        self._execute(
            """
            INSERT INTO feature_toggles
                   (tenant_id, module_key, is_enabled, changed_by, disable_confirmation)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, module_key)
            DO UPDATE SET is_enabled           = EXCLUDED.is_enabled,
                          changed_by           = EXCLUDED.changed_by,
                          changed_at           = now(),
                          disable_confirmation = EXCLUDED.disable_confirmation
            """,
            (tenant_id, module_key, enabled, changed_by, confirmation),
        )

    def is_structural(self, tenant_id: TenantId, module_key: str) -> bool:
        row = self._fetch_one(
            "SELECT is_structural FROM feature_toggles WHERE tenant_id = %s AND module_key = %s",
            (tenant_id, module_key),
        )
        return bool(row["is_structural"]) if row else False


# --------------------------------------------------------------------------- #
# PermissionFlagRepository
# --------------------------------------------------------------------------- #


class PostgresPermissionFlagRepository(_BaseRepository):
    """İcazə registri (`permission_flags` — tenant-dan ASILI DEYİL).

    Cədvəldə `tenant_id` yoxdur: flag kataloqu bütün quraşdırma üçün ortaqdır,
    tenant-a xas olan yalnız hansı rolun hansı flag-i ALDIĞIDIR
    (`position_permissions`).
    """

    _SELECT: Final = """
        SELECT code, category, hardlock_level, is_anti_fraud,
               is_camera_only, excludes_camera_role
        FROM permission_flags
    """

    def get(self, code: str) -> PermissionFlag | None:
        row = self._fetch_one(f"{self._SELECT} WHERE code = %s", (code,))
        return self._to_flag(row) if row else None

    def list_all(self) -> list[PermissionFlag]:
        rows = self._fetch_all(f"{self._SELECT} ORDER BY category, code", ())
        return [self._to_flag(row) for row in rows]

    def create(self, flag: PermissionFlag, *, created_by: EmployeeId) -> None:
        """Yeni flag yaradır (YALNIZ Root — icazə yoxlaması use case-dədir).

        `ON CONFLICT DO NOTHING` İŞLƏDİLMİR: təkrar kod səssizcə udulsaydı,
        Root yeni flag yaratdığını sanardı, əslində köhnəsi qalardı.
        """
        self._execute(
            """
            INSERT INTO permission_flags
                   (code, category, name_az, hardlock_level, is_anti_fraud,
                    is_camera_only, excludes_camera_role, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                flag.code,
                flag.category,
                flag.code,
                int(flag.hardlock),
                flag.is_anti_fraud,
                flag.is_camera_only,
                flag.excludes_camera_role,
                created_by,
            ),
        )

    @staticmethod
    def _to_flag(row: dict[str, Any]) -> PermissionFlag:
        return PermissionFlag(
            code=row["code"],
            category=row["category"],
            hardlock=HardlockLevel(row["hardlock_level"]),
            is_anti_fraud=bool(row["is_anti_fraud"]),
            is_camera_only=bool(row["is_camera_only"]),
            excludes_camera_role=bool(row["excludes_camera_role"]),
        )


# --------------------------------------------------------------------------- #
# LeaveTypeRepository
# --------------------------------------------------------------------------- #


def _break_kind_or_none(raw: object) -> BreakKind | None:
    """`leave_types.break_kind` sütununu domen enum-una çevirir.

    NAMƏLUM DƏYƏR İSTİSNA ATMIR: sütun `TEXT`-dir və `CHECK` onu iki dəyərlə
    məhdudlaşdırsa da, gələcək bir miqrasiya üçüncü növ əlavə edə bilər. Köhnə
    tətbiq həmin sətri "adi icazə növü" kimi oxuyub işləməyə davam etməlidir —
    kataloq ekranının bütövlükdə açılmaması qüsurun cəzasını istifadəçiyə
    verərdi (`_limit_key_or_none` ilə eyni fəlsəfə).
    """
    if raw is None:
        return None
    try:
        return BreakKind(str(raw))
    except ValueError:
        return None


class PostgresLeaveTypeRepository(_BaseRepository):
    """İcazə növləri kataloqu (`leave_types`)."""

    def get_default_duration(self, leave_type_id: LeaveTypeId) -> int | None:
        row = self._fetch_one(
            """
            SELECT default_duration_minutes
            FROM leave_types
            WHERE id = %s AND tenant_id = %s
            """,
            (leave_type_id, self._tenant),
        )
        return int(row["default_duration_minutes"]) if row else None

    def list_active(self, tenant_id: TenantId) -> list[dict[str, Any]]:
        """Xam sətirlər — köhnə çağırış nöqtələri üçün saxlanılır."""
        return self._fetch_all(
            """
            SELECT id, name_az, default_duration_minutes
            FROM leave_types
            WHERE tenant_id = %s AND is_active
            ORDER BY name_az
            """,
            (tenant_id,),
        )

    def list_all(self, tenant_id: TenantId, *, include_inactive: bool = False) -> list[LeaveType]:
        """Kataloq ekranı üçün domen obyektləri (bölmə 4).

        `list_active()`-dən fərqi: bu, `LeaveType` value object-i qaytarır və
        deaktivləri də göstərə bilir — idarəetmə ekranı onları yenidən
        aktivləşdirə bilməlidir.
        """
        sql = """
            SELECT id, tenant_id, name_az, default_duration_minutes, is_active, break_kind
            FROM leave_types
            WHERE tenant_id = %s
        """
        if not include_inactive:
            sql += " AND is_active"
        rows = self._fetch_all(sql + " ORDER BY name_az", (tenant_id,))
        # TAVAN SORĞU BAŞINA BİR DƏFƏ oxunur, sətir başına YOX: kataloq onlarla
        # sətirdən ibarətdir və hər biri üçün `system_limits`-ə getmək eyni
        # cavabı təkrar-təkrar gətirərdi.
        ceiling = self.max_duration_minutes(tenant_id)
        return [self._hydrate(row, ceiling) for row in rows]

    def max_duration_minutes(self, tenant_id: TenantId) -> int:
        """ROOT tavanı (`LEAVE_TYPE_MAX_DURATION_MINUTES`) — mənbə `system_limits`.

        ────────────────────────────────────────────────────────────────────
        NİYƏ OXU YOLU DA TAVANI BİLMƏLİDİR
        ────────────────────────────────────────────────────────────────────
        Tavan yalnız YAZI anında yoxlanılsaydı bəs edərdi — LAKİN `LeaveType`
        həm də bazadan BƏRPA edilərkən qurulur. Root tavanı 720→1200-ə
        qaldırıb 900 dəqiqəlik növ yaratsaydı, növbəti oxu modul fallback-ı
        (720) ilə həmin sətri RƏDD edərdi və kataloq ekranı bütövlükdə
        açılmazdı. Yəni oxu və yazı EYNİ tavanı görməlidir.

        `PostgresSystemLimits` EYNİ bağlantı üzərində qurulur — ikinci
        bağlantı açılmır və dəyər eyni tranzaksiyadan oxunur.
        """
        key = SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES
        return PostgresSystemLimits(self._conn, self._context).get_int(
            tenant_id, key.value, MAX_LEAVE_DURATION_MINUTES
        )

    def save(self, tenant_id: TenantId, entry: LeaveType, *, changed_by: EmployeeId) -> None:
        self._execute(
            """
            INSERT INTO leave_types
                (id, tenant_id, name_az, default_duration_minutes, is_active)
            VALUES (COALESCE(%s, gen_random_uuid()), %s, %s, %s, %s)
            ON CONFLICT (tenant_id, name_az)
            DO UPDATE SET default_duration_minutes = EXCLUDED.default_duration_minutes,
                          is_active                = EXCLUDED.is_active
            """,
            (
                entry.leave_type_id,
                tenant_id,
                entry.name,
                entry.default_duration_minutes,
                entry.is_active,
            ),
        )
        _log.info(
            "LEAVE_TYPE_SAVED",
            extra={"name": entry.name, "changed_by": str(changed_by)},
        )

    def deactivate(
        self, tenant_id: TenantId, leave_type_id: LeaveTypeId, *, changed_by: EmployeeId
    ) -> None:
        """SOFT DELETE — keçmiş icazə sorğuları öz növünü saxlayır."""
        self._execute(
            "UPDATE leave_types SET is_active = FALSE WHERE id = %s AND tenant_id = %s",
            (leave_type_id, tenant_id),
        )
        _log.info(
            "LEAVE_TYPE_DEACTIVATED",
            extra={"leave_type_id": str(leave_type_id), "changed_by": str(changed_by)},
        )

    def break_kind_of(self, leave_type_id: LeaveTypeId) -> BreakKind | None:
        """Seçilmiş növ sistem fasiləsidirmi (nahar.md, migrations/045).

        `is_active` ŞƏRTİ QOYULMUR: sual "bu sətir hansı fasilədir", "seçilə
        bilərmi" DEYİL. HR növü deaktiv edəndən sonra da köhnə ekrandan gələn
        sorğu doğru sayğaca düşməlidir — əks halda sayğac səssizcə yanlış
        növə yazılardı.
        """
        row = self._fetch_one(
            "SELECT break_kind FROM leave_types WHERE id = %s AND tenant_id = %s",
            (leave_type_id, self._tenant),
        )
        return _break_kind_or_none(row.get("break_kind") if row else None)

    @staticmethod
    def _hydrate(row: dict[str, Any], ceiling: int) -> LeaveType:
        is_active = bool(row.get("is_active", True))
        return LeaveType(
            break_kind=_break_kind_or_none(row.get("break_kind")),
            # ROOT tavanı ötürülür — bax `max_duration_minutes()` başlığı.
            max_duration_minutes=ceiling,
            name=str(row["name_az"]),
            tenant_id=TenantId(row["tenant_id"]),
            is_active=is_active,
            # Sxemdə deaktivləşdirmə anı üçün sütun yoxdur; domen isə onu
            # tələb edir. UNIX epoxası "tarixi bilinmir" nişanıdır — uydurma
            # tarix yazmaqdansa açıq şəkildə "məlum deyil" göstərmək daha
            # dürüstdür (bax migration 010-dakı eyni prinsip).
            deactivated_at=None if is_active else datetime(1970, 1, 1, tzinfo=UTC),
            leave_type_id=row["id"],
            default_duration_minutes=int(row.get("default_duration_minutes") or 0),
        )


# --------------------------------------------------------------------------- #
# ShiftRepository
# --------------------------------------------------------------------------- #


class PostgresShiftRepository(_BaseRepository):
    """Növbə planı (`shift_assignments` + `work_modes`)."""

    def is_off_day(self, employee_id: EmployeeId, work_date: date) -> bool:
        """İstirahət günüdürmü.

        Sətir YOXDURSA `False` qaytarılır — plan qurulmayıb deməkdir, iş günü
        sayılır. `True` qaytarsaydıq, planlaşdırılmamış işçi üçün gecikmə heç
        vaxt hesablanmazdı və cərimə sistemi səssizcə söndürülərdi.
        """
        row = self._fetch_one(
            """
            SELECT is_off_day
            FROM shift_assignments
            WHERE employee_id = %s AND shift_date = %s AND tenant_id = %s
            """,
            (employee_id, work_date, self._tenant),
        )
        return bool(row["is_off_day"]) if row else False

    def scheduled_start(self, employee_id: EmployeeId, work_date: date) -> datetime | None:
        """Planlaşdırılmış başlanğıc vaxtı — gecikmə hesablamasının bazası.

        İstirahət günündə və ya plan olmadıqda `None` qaytarılır; çağıran
        tərəf o zaman gecikmə hesablamır.
        """
        row = self._fetch_one(
            """
            SELECT (sa.shift_date + wm.start_time) AS starts_at
            FROM shift_assignments sa
            JOIN work_modes wm ON wm.id = sa.work_mode_id
            WHERE sa.employee_id = %s
              AND sa.shift_date = %s
              AND sa.tenant_id = %s
              AND NOT sa.is_off_day
            """,
            (employee_id, work_date, self._tenant),
        )
        return row["starts_at"] if row else None

    # ------------------------- Shift Matrix (bölmə 3) ------------------------ #

    _SELECT_ASSIGNMENT = """
        SELECT id, tenant_id, employee_id, shift_date, work_mode_id,
               is_off_day, assigned_by, source
        FROM shift_assignments
    """

    def get_assignment(self, employee_id: EmployeeId, work_date: date) -> ShiftAssignment | None:
        row = self._fetch_one(
            f"{self._SELECT_ASSIGNMENT} WHERE employee_id = %s AND shift_date = %s "
            f"AND tenant_id = %s",
            (employee_id, work_date, self._tenant),
        )
        return _row_to_assignment(row) if row else None

    def list_range(
        self,
        tenant_id: TenantId,
        *,
        start: date,
        end: date,
        store_id: StoreId | None = None,
        employee_ids: list[EmployeeId] | None = None,
    ) -> list[ShiftAssignment]:
        """Təqvim dövrü — scoping süzgəcləri SQL-də tətbiq olunur.

        Süzgəci Python-da etmək 21 filialın bir ayını (≈6000 sətir) yaddaşa
        gətirib bir işçinin 30 gününü seçmək demək olardı.
        """
        clauses = ["sa.tenant_id = %s", "sa.shift_date BETWEEN %s AND %s"]
        params: list[Any] = [tenant_id, start, end]

        if store_id is not None:
            clauses.append("e.store_id = %s")
            params.append(store_id)
        if employee_ids is not None:
            if not employee_ids:
                return []
            clauses.append("sa.employee_id = ANY(%s)")
            params.append(list(employee_ids))

        rows = self._fetch_all(
            f"""
            SELECT sa.id, sa.tenant_id, sa.employee_id, sa.shift_date,
                   sa.work_mode_id, sa.is_off_day, sa.assigned_by, sa.source
            FROM shift_assignments sa
            JOIN employees e ON e.id = sa.employee_id
            WHERE {" AND ".join(clauses)}
            ORDER BY sa.shift_date, sa.employee_id
            """,  # noqa: S608 — şərtlər SABİT sətir siyahısındandır, dəyərlər %s ilə bağlanır
            tuple(params),
        )
        return [_row_to_assignment(row) for row in rows]

    def save_assignment(self, assignment: ShiftAssignment) -> None:
        """UPSERT — `(employee_id, shift_date)` DB-də unikaldır.

        `ON CONFLICT` istifadə olunur ki, "əvvəlcə oxu, sonra yaz" yarışı
        yaranmasın: iki admin eyni hüceyrəni eyni anda dəyişsə, ikincisi
        birincinin üstündən yazır və heç biri xəta almır.
        """
        self._execute(
            """
            INSERT INTO shift_assignments
                (id, tenant_id, employee_id, shift_date, work_mode_id,
                 is_off_day, assigned_by, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, shift_date) DO UPDATE
                SET work_mode_id = EXCLUDED.work_mode_id,
                    is_off_day   = EXCLUDED.is_off_day,
                    assigned_by  = EXCLUDED.assigned_by,
                    source       = EXCLUDED.source
            """,
            (
                assignment.assignment_id,
                assignment.tenant_id,
                assignment.employee_id,
                assignment.shift_date,
                assignment.work_mode_id,
                assignment.is_off_day,
                assignment.assigned_by,
                assignment.source.value,
            ),
        )

    def clear_assignment(self, employee_id: EmployeeId, work_date: date) -> None:
        self._execute(
            """
            DELETE FROM shift_assignments
            WHERE employee_id = %s AND shift_date = %s AND tenant_id = %s
            """,
            (employee_id, work_date, self._tenant),
        )


def _row_to_assignment(row: dict[str, Any]) -> ShiftAssignment:
    return ShiftAssignment(
        assignment_id=row["id"],
        tenant_id=row["tenant_id"],
        employee_id=row["employee_id"],
        shift_date=row["shift_date"],
        is_off_day=bool(row["is_off_day"]),
        work_mode_id=row["work_mode_id"],
        assigned_by=row["assigned_by"],
        source=ShiftSource(row["source"]),
    )


# --------------------------------------------------------------------------- #
# CameraAssignmentRepository
# --------------------------------------------------------------------------- #


class PostgresCameraAssignmentRepository(_BaseRepository):
    """Kamera Operatoru → mağaza təyinatı (`camera_operator_store_assignment`).

    FAIL-SAFE (bölmə 4): təyinat yoxdursa BOŞ siyahı qaytarılır və operator
    heç nə görmür. Defolt "hər şeyi göstər" DEYİL — səhvən təyinatsız qalan
    operator bütün 21 filialın məlumatını görməməlidir.
    """

    def stores_for_operator(self, operator_id: EmployeeId) -> list[StoreId]:
        rows = self._fetch_all(
            """
            SELECT a.store_id
            FROM camera_operator_store_assignment a
            JOIN employees e ON e.id = a.operator_id
            WHERE a.operator_id = %s AND e.tenant_id = %s
            ORDER BY a.assigned_at
            """,
            (operator_id, self._tenant),
        )
        return [row["store_id"] for row in rows]

    def assign(
        self, operator_id: EmployeeId, store_id: StoreId, *, assigned_by: EmployeeId
    ) -> None:
        self._execute(
            """
            INSERT INTO camera_operator_store_assignment (operator_id, store_id, assigned_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (operator_id, store_id) DO NOTHING
            """,
            (operator_id, store_id, assigned_by),
        )

    def unassign(self, operator_id: EmployeeId, store_id: StoreId) -> None:
        self._execute(
            """
            DELETE FROM camera_operator_store_assignment
            WHERE operator_id = %s AND store_id = %s
            """,
            (operator_id, store_id),
        )


class PostgresStoreWriter(_BaseRepository):
    """`stores` cədvəlinə yazma — İlk Quraşdırma Sihirbazı və İnfrastruktur paneli.

    `tenant_id` arqument kimi ötürülür, `self._tenant`-dan GÖTÜRÜLMÜR: sihirbaz
    məhz tenant konteksti hələ tam qurulmamış anda işləyir və orada açıq
    ötürülən dəyər daha etibarlıdır.
    """

    def create(
        self,
        *,
        store_id: StoreId,
        tenant_id: TenantId,
        code: str,
        name: str,
        brand: str,
        address: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO stores (id, tenant_id, code, name, brand, address)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, code) DO UPDATE
                SET name    = EXCLUDED.name,
                    brand   = EXCLUDED.brand,
                    address = EXCLUDED.address
            """,
            (store_id, tenant_id, code, name, brand, address or None),
        )

    def get_id_by_code(self, tenant_id: TenantId, code: str) -> StoreId | None:
        """Toplu idxal CSV-sindəki insan-oxunaqlı mağaza kodunu UUID-ə çevirir.

        `is_active` süzgəci QƏSDƏN YOXDUR: deaktiv mağazaya işçi təyin etmək
        istəyi ekran/tətbiq qatının biznes qərarıdır (məs. bağlanmış filialın
        arxiv işçisi), bu port isə YALNIZ "bu kod haraya işarələyir?" sualına
        cavab verir.
        """
        row = self._fetch_one(
            "SELECT id FROM stores WHERE tenant_id = %s AND code = %s",
            (tenant_id, code),
        )
        return row["id"] if row else None


__all__ = [
    "STRUCTURAL_CONFIRMATION_REQUIRED",
    "PostgresCameraAssignmentRepository",
    "PostgresFeatureToggles",
    "PostgresLeaveTypeRepository",
    "PostgresPermissionFlagRepository",
    "PostgresShiftRepository",
    "PostgresStoreWriter",
    "PostgresSystemLimits",
]
