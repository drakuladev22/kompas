"""Supabase/PostgreSQL repository-ləri (spesifikasiya bölmə 2) — Faza 3.2.

QAYDA (bölmə 2): **100% Parameterized SQL Queries.** Bu faylda heç bir SQL
sətir birləşdirmə (`f"..."`, `+`, `%`) ilə qurulmur — bütün dəyərlər `%s`
placeholder-ları ilə ötürülür. Yeganə istisna: sabit sütun adları, onlar da
kod daxilində literal kimi yazılır, kənardan gəlmir.

RLS: bu repo-lar YALNIZ aktiv `PostgresUnitOfWork` daxilində yaradılır və
tranzaksiya artıq `SET LOCAL app.tenant_id` icra edib (SEC-008). Sorğularda
`tenant_id` şərti ƏLAVƏ olaraq yazılır — RLS sıradan çıxsa belə (məs. tətbiq
səhvən owner rolu ilə qoşulsa) izolyasiya qalsın.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from psycopg import errors as pg_errors

from src.application.use_cases.fine_management import (
    ConcurrentVerificationConflictError,
    DuplicateFineSubmissionError,
)
from src.application.use_cases.leave_verification import OperationNotPermittedError
from src.application.use_cases.user_management import OffboardingSignals, OpenFineExposure
from src.domain.entities.attendance_record import AttendanceRecord, CheckInStatus
from src.domain.entities.employee import Employee
from src.domain.entities.fine import EXPORTABLE_STATUSES, Fine, FineStatus
from src.domain.entities.leave_request import LeaveRequest, LeaveStatus
from src.domain.entities.position import Position
from src.domain.entities.task import TaskStatus
from src.domain.value_objects.authorization import RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import (
    AttendanceRecordId,
    EmployeeId,
    FineId,
    LeaveRequestId,
    PositionId,
    StoreId,
    TenantId,
)
from src.infrastructure.persistence.connection import TenantContextError
from src.infrastructure.persistence.mappers import (
    Credentials,
    apply_overrides,
    apply_position_flags,
    apply_store_assignments,
    attendance_from_row,
    attendance_to_params,
    credentials_from_row,
    employee_from_row,
    fine_from_row,
    fine_to_params,
    leave_request_from_row,
    leave_request_to_params,
    position_from_row,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from psycopg import Connection

    from src.infrastructure.persistence.connection import TenantContext

_log = get_logger(__name__)


class _BaseRepository:
    """Ortaq bağlantı/kontekst saxlayıcısı."""

    def __init__(self, conn: Connection[dict[str, Any]], context: TenantContext) -> None:
        self._conn = conn
        self._context = context

    @property
    def _tenant(self) -> TenantId:
        return self._context.tenant_id

    def _require_matching_tenant(self, tenant_id: TenantId) -> TenantId:
        """Çağıranın `tenant_id` arqumenti bağlantının ÖZ kontekstiylə UYĞUNDUR MU.

        INF2-02 (dövrə 2 audit): bir sıra `list_*()`-tipli metod imzası
        Protocol-un tələb etdiyi `tenant_id` arqumentini QƏBUL EDİR (ports.py
        çağıranın kontekstindən asılı olmayan sabit imza istəyir), lakin
        sorğuda `self._tenant`-i YOX, məhz bu arqumenti işlədirdi. RLS
        (`WITH CHECK`/`USING (tenant_id = current_tenant_id())`) hələ də
        SIZMANIN qarşısını alır — nəticə səhv `tenant_id`-lə YALNIZ BOŞ qayıda
        bilər, BAŞQA kirayəçinin sətri HEÇ VAXT — amma "heç nə yoxdur" ilə
        "çağıran KOD SƏHVİDİR" arasındakı fərq itir: operator "məlumat yoxdur"
        zənn edir, halbuki arxada YANLIŞ `tenant_id` ötürülüb.

        Bu metod o fərqi GERİ QAYTARIR: SÜKUTLA `self._tenant`-ə keçmək əvəzinə
        (bu, uyğunsuzluğu YENƏ gizlədərdi, sadəcə yerini dəyişdirərdi),
        uyğunsuzluqda GURULTULU `TenantContextError` atır — proqramçı səhvi
        SƏSSİZ qalmamalıdır. Uyğunluq varsa `self._tenant`-i qaytarır ki,
        çağıran sorğuda TƏK mənbədən (bağlantının kontekstindən) istifadə etsin.

        ──────────────────────────────────────────────────────────────────────
        BU QATIN İKİ NAXIŞLI OLDUĞU BİLİNMƏLİDİR — HƏLƏ TAM TƏTBİQ OLUNMAYIB
        ──────────────────────────────────────────────────────────────────────
        Bu metod `persistence/`-in HƏDƏF naxışıdır, KÖNÜLLÜ HAMISINA yayılan
        DEYİL. Dövrə 2 audit ~154 metodu (~40 fayl) AŞKARLADI ki, `tenant_id:
        TenantId` arqumentini QƏBUL EDİR, lakin `self._tenant`-i YOX, birbaşa
        arqumentin ÖZÜNÜ işlədir — yəni bu qorumadan KEÇMİR. Yalnız BEŞ fayl
        (`auth_session_repository.py`, `security_event_repository.py`,
        `telegram_repositories.py`, VƏ dövrə 2-də əlavə olunan
        `exception_repositories.py`/`open_shift_repository.py`/
        `support_repositories.py`/`announcement_repository.py`) bu metodu
        işlədir və ya `self._tenant`-i birbaşa istifadə edir.

        Qalan ~154 metod TOPLU şəkildə KÖÇÜRÜLMÜR — SƏBƏBLƏR:
          1. Miqyas: 40 fayl, hər biri öz sorğu quruluşuna görə ayrıca yoxlama
             tələb edir — bir dövrənin ORTASINDA yarımçıq/izlənilməz olardı.
          2. TƏHLÜKƏSİZLİK DEŞİYİ DEYİL: RLS (`WITH CHECK`/`USING (tenant_id =
             current_tenant_id())`) sızmanın qarşısını onsuz da alır — itən
             şey YALNIZ "boş nəticə" ilə "kodda xəta" arasındakı fərqdir
             (dərinlikdə müdafiə güzəşti, kritik boşluq deyil).
          3. Ayrıca planlaşdırılmalı, ayrıca test olunmalı, ayrıca commit
             olunmalı bir işdir (ARCHITECT-in dövrə 2 qərarı).

        **YENİ metod yazan növbəti oxucu üçün qayda:** YENİ yazılan hər
        `tenant_id` qəbul edən repository metodu bu funksiyanı ÇAĞIRMALIDIR
        — "köhnə 154-ə bənzət" YOX, "yeni beşliyə bənzət". Rəqəm (154) qəsdən
        BURADA SAXLANILIR — vaxtla köhnəlsə belə, qalan işin BÖYÜKLÜK
        SIRASINI göstərir.
        """
        if tenant_id != self._tenant:
            raise TenantContextError(
                "Çağıran `tenant_id` bağlantının ÖZ kontekstindən FƏRQLİDİR — "
                "proqram xətası (bax `_require_matching_tenant` şərhi)",
                context={
                    "argument_tenant_id": str(tenant_id),
                    "connection_tenant_id": str(self._tenant),
                },
            )
        return self._tenant

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def _execute(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


# --------------------------------------------------------------------------- #
# Position
# --------------------------------------------------------------------------- #


class PostgresPositionRepository(_BaseRepository):
    # `is_store_tier` (T6, DEEP-GAP dövrə auditi, migrations/080) — `is_camera_
    # type`-ın EYNİ naxışı, `position_from_row`-un oxuduğu sütun.
    _SELECT = """
        SELECT id, tenant_id, code, name_az, priority, is_system,
               is_camera_type, is_store_tier, is_active
        FROM positions
    """

    def get(self, position_id: PositionId) -> Position | None:
        row = self._fetch_one(self._SELECT + " WHERE id = %s", (position_id,))
        return self._hydrate(row) if row else None

    def get_by_code(self, tenant_id: TenantId, code: str) -> Position | None:
        row = self._fetch_one(
            self._SELECT + " WHERE tenant_id = %s AND code = %s", (tenant_id, code)
        )
        return self._hydrate(row) if row else None

    def list_for_tenant(self, tenant_id: TenantId) -> list[Position]:
        rows = self._fetch_all(
            self._SELECT + " WHERE tenant_id = %s ORDER BY priority, code",
            (tenant_id,),
        )
        return [self._hydrate(row) for row in rows]

    def save(self, position: Position) -> None:
        self._execute(
            """
            INSERT INTO positions
                (id, tenant_id, code, name_az, priority, is_system,
                 is_camera_type, is_store_tier, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name_az        = EXCLUDED.name_az,
                priority       = EXCLUDED.priority,
                is_camera_type = EXCLUDED.is_camera_type,
                is_store_tier  = EXCLUDED.is_store_tier,
                is_active      = EXCLUDED.is_active
            """,
            (
                position.id,
                position.tenant_id,
                position.code,
                position.name_az,
                int(position.priority),
                position.is_system,
                position.is_camera_type,
                position.is_store_tier,
                position.is_active,
            ),
        )
        self._sync_flags(position)

    def _sync_flags(self, position: Position) -> None:
        """Rol → flag təyinatını DB ilə uzlaşdırır.

        DB trigger-ləri (anti-fraud, hardlock) burada da işə düşür — yəni
        domen qatı yan keçilsə belə qadağan olunmuş flag DB-yə düşmür.

        ──────────────────────────────────────────────────────────────────────
        `granted_by` NİYƏ SESSİYA KONTEKSTİNDƏN GƏLİR
        ──────────────────────────────────────────────────────────────────────
        `enforce_grantor_owns_flag()` (miqrasiya 014) Self-Escalation Guard-ın
        DB tərəfidir və qərarını `NEW.granted_by` sütununa görə verir. Sütun
        BOŞ qaldıqda trigger onu SEED yazısı sayır və yoxlamadan buraxır —
        yəni İcazə Matrisi ekranından gələn hər rol dəyişikliyi DB qapısını
        sükutla yan keçirdi və qayda yalnız BİR yerdə (domendə) qalırdı.
        CLAUDE.md bölmə 5 isə hər qaydanın İKİ yerdə olmasını tələb edir.

        Dəyər `app.user_id`-dən oxunur — `UnitOfWork` onu `SET LOCAL` ilə
        qoyur (`_apply_tenant_context`). Metod imzası DƏYİŞMİR: `granted_by`
        parametri əlavə etsəydik `PositionRepository` portunu və onun bütün
        çağırış yerlərini dəyişmək lazım gələrdi, halbuki aktor onsuz da
        tranzaksiya kontekstindədir.

        `NULLIF(..., '')` vacibdir: `user_id` verilməyən sessiyalarda (ilk
        quraşdırma, planlayıcı işləri) parametr BOŞ SƏTİRDİR və `::uuid`
        çevirməsi xəta verərdi — `NULL` isə seed istisnasına düşür, yəni
        köhnə davranış olduğu kimi qalır.
        """
        self._execute(
            "DELETE FROM position_permissions WHERE position_id = %s AND flag_code <> ALL(%s)",
            (position.id, list(position.granted_flags) or [""]),
        )
        for flag_code in position.granted_flags:
            self._execute(
                """
                INSERT INTO position_permissions (position_id, flag_code, granted, granted_by)
                VALUES (%s, %s, TRUE, NULLIF(current_setting('app.user_id', TRUE), '')::uuid)
                ON CONFLICT (position_id, flag_code)
                DO UPDATE SET granted    = TRUE,
                              -- Kontekstsiz yazı MÖVCUD "verən"i silməməlidir:
                              -- planlayıcı işi bir sətrə toxunduqda "kim verdi"
                              -- sualının cavabı itərdi.
                              granted_by = COALESCE(
                                  EXCLUDED.granted_by, position_permissions.granted_by
                              )
                """,
                (position.id, flag_code),
            )

    def _hydrate(self, row: dict[str, Any]) -> Position:
        position = position_from_row(row)
        flags = self._fetch_all(
            """
            SELECT flag_code FROM position_permissions
            WHERE position_id = %s AND granted
            """,
            (position.id,),
        )
        return apply_position_flags(position, [f["flag_code"] for f in flags])


# --------------------------------------------------------------------------- #
# Employee
# --------------------------------------------------------------------------- #


class PostgresEmployeeRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, store_id, position_id, first_name, last_name,
               username, notification_email, password_hash, must_change_password,
               pin_hash, pin_failed_attempts, pin_locked_until, pepper_version,
               profile_photo_url, hire_date, date_of_birth, is_active
        FROM employees
    """

    def get(self, employee_id: EmployeeId) -> Employee | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (employee_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def get_by_username(self, tenant_id: TenantId, username: Username) -> Employee | None:
        # `username` sütunu CITEXT-dir — böyük/kiçik hərf fərqi DB tərəfindən
        # nəzərə alınmır, ona görə burada əlavə `lower()` LAZIM DEYİL
        # (əlavə edilsəydi indeksdən istifadə də pozulardı).
        row = self._fetch_one(
            self._SELECT + " WHERE tenant_id = %s AND username = %s",
            (tenant_id, str(username)),
        )
        return self._hydrate(row) if row else None

    def find_by_pin_candidates(self, tenant_id: TenantId, store_id: StoreId) -> list[Employee]:
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND store_id = %s
              AND is_active AND pin_hash IS NOT NULL
            """,
            (tenant_id, store_id),
        )
        return [self._hydrate(row) for row in rows]

    def credentials_for(self, employee_id: EmployeeId) -> Credentials | None:
        """Sirr materialı — entity-dən AYRI (log-a düşməsin deyə)."""
        row = self._fetch_one(
            """
            SELECT id, pin_hash, password_hash, pepper_version
            FROM employees WHERE id = %s AND tenant_id = %s
            """,
            (employee_id, self._tenant),
        )
        return credentials_from_row(row) if row else None

    def count_active_with_flag(self, tenant_id: TenantId, flag_code: str) -> int:
        """Dual-Control Deadlock Guard üçün — EFFEKTİV icazə (override daxil)."""
        row = self._fetch_one(
            """
            SELECT count(*)::int AS n
            FROM v_effective_permissions v
            JOIN employees e ON e.id = v.user_id
            WHERE v.tenant_id = %s AND v.flag_code = %s AND v.is_granted
              AND e.is_active
            """,
            (tenant_id, flag_code),
        )
        return int(row["n"]) if row else 0

    def count_active_ranked_at_or_above(self, tenant_id: TenantId, priority: RolePriority) -> int:
        """İyerarxiya pilləsinə görə sayğac (SETUP-3) — `<=`, çünki 0 ən yüksəkdir.

        `v_effective_permissions` İSTİFADƏ EDİLMİR: sual səlahiyyət haqqında
        deyil, PİLLƏ haqqındadır. Flag dəsti Root tərəfindən dəyişdirilə bilər,
        pillə isə rolun tərifidir — «tenant sahibsiz qaldımı?» sualının cavabı
        konfiqurasiyadan asılı olmamalıdır.
        """
        row = self._fetch_one(
            """
            SELECT count(*)::int AS n
            FROM employees e
            JOIN positions p ON p.id = e.position_id
            WHERE e.tenant_id = %s AND e.is_active AND p.is_active AND p.priority <= %s
            """,
            (tenant_id, int(priority)),
        )
        return int(row["n"]) if row else 0

    def save(self, employee: Employee) -> None:
        """Entity-dən gələn sahələri yeniləyir.

        SİRRLƏRƏ TOXUNMUR: `pin_hash`/`password_hash` burada YAZILMIR —
        onlar üçün ayrıca `update_credentials()` var. Beləliklə adi `save()`
        çağırışı təsadüfən sirri sıfırlaya bilməz.

        `username` DƏ BURADA YAZILMIR: giriş identifikatorunun dəyişməsi
        ayrıca, audit-lənən əməliyyatdır (`rename_username()`) — adi profil
        yeniləməsi ilə birlikdə sükutla baş verməməlidir.

        `referred_by_employee_id` BURADA YAZILMIR: Faza 3.5 (`entities/
        employee.py` şərhi) bunu "tarixi fakt olaraq daimi qalır" deyə
        təyin edir — yalnız `insert()`-də (yaranış anında) yazılır.

        `deactivated_at` BURADA YAZILMIR: TIME-1 trigger-i (migrations/096)
        `is_active` keçidindən avtomatik hesablayır — client dəyəri qəbul
        edilmir, ötürülsə belə görməzdən gəlinərdi.

        `profile_photo_url`/`date_of_birth`/`scheduled_deactivation_date`/
        `data_anonymized_at` YENİ ƏLAVƏ OLUNUB (migrations/096 tapıntısı):
        ilk ikisi ARTIQ domen entity-sində mövcud idi, lakin `save()` onları
        HEÇ VAXT yazmırdı — `Employee.anonymize_personal_data()` (Faza 3.2)
        məhz bu iki sahəni SIFIRLAYIR, yəni onlarsız anonimləşdirmə
        `data_anonymized_at`-ı doldurub HƏQİQİ PII-ni (şəkil, doğum tarixi)
        bazada SAXLAYARDI — yanlış uyğunluq siqnalı.
        """
        self._execute(
            """
            UPDATE employees SET
                store_id                    = %s,
                position_id                 = %s,
                first_name                  = %s,
                last_name                   = %s,
                notification_email          = %s,
                must_change_password        = %s,
                pin_failed_attempts         = %s,
                pin_locked_until             = %s,
                is_active                   = %s,
                profile_photo_url           = %s,
                date_of_birth               = %s,
                scheduled_deactivation_date = %s,
                data_anonymized_at          = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (
                employee.store_id,
                employee.position.id,
                employee.first_name,
                employee.last_name,
                str(employee.notification_email) if employee.notification_email else None,
                employee.must_change_password,
                employee.pin_security.failed_attempts,
                employee.pin_security.locked_until,
                employee.is_active,
                employee.profile_photo_url,
                employee.date_of_birth,
                employee.scheduled_deactivation_date,
                employee.data_anonymized_at,
                employee.id,
                self._tenant,
            ),
        )
        self._sync_overrides(employee)
        self._sync_store_assignments(employee)

    def create(
        self,
        employee: Employee,
        *,
        raw_password: str | None = None,
        raw_pin: str | None = None,
    ) -> None:
        """Yeni işçi sətrini SİRRİ İLƏ BİRLİKDƏ yaradır.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `save()` BUNU EDƏ BİLMİR
        ──────────────────────────────────────────────────────────────────────
        `save()` `UPDATE`-dir və olmayan sətri yaratmır — yəni yeni işçi üçün
        SIFIR sətir dəyişdirir və heç bir xəta vermir. İlk Quraşdırma Sihirbazı
        məhz buna görə canlı bazada işləmirdi: Root sətri yaranmır, ardınca
        `audit_logs.actor_id` xarici açarı «Key is not present in table
        "employees"» ilə çökürdü. Nasazlıq yaddaşdakı sahtələrdə GÖRÜNMÜRDÜ,
        çünki orada `save()` upsert kimi davranır.

        `save()`-i upsert etmək DƏ mümkün deyil: `chk_employee_auth` hər sətrin
        ən azı bir autentifikasiya vasitəsi ilə YARANMASINI tələb edir
        (`pin_hash`, və ya `username` + `password_hash`), `Employee` entity-si
        isə heşləri SAXLAMIR. Ona görə sətir və sirri BİR ifadədə yazılır.

        Heşləmə burada olur (`set_password` ilə eyni səbəb): use case xam
        şifrəni alır, heşi görmür.
        """
        hashing = self._hashing()
        credentials = Credentials(
            employee_id=employee.id,
            password_hash=hashing.hash_password(raw_password) if raw_password else None,
            pin_hash=(hashing.hash_pin(raw_pin, employee_id=str(employee.id)) if raw_pin else None),
            pepper_version=hashing.current_pepper_version,
        )
        self.insert(employee, credentials)
        self._sync_overrides(employee)
        self._sync_store_assignments(employee)

    def insert(self, employee: Employee, credentials: Credentials) -> None:
        """Yeni işçi — sirrlərlə birlikdə (yalnız yaradılış anında)."""
        self._execute(
            """
            INSERT INTO employees
                (id, tenant_id, store_id, position_id, first_name, last_name,
                 username, notification_email, password_hash, must_change_password,
                 pin_hash, pepper_version, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                employee.id,
                employee.tenant_id,
                employee.store_id,
                employee.position.id,
                employee.first_name,
                employee.last_name,
                str(employee.username) if employee.username else None,
                str(employee.notification_email) if employee.notification_email else None,
                credentials.password_hash,
                employee.must_change_password,
                credentials.pin_hash,
                credentials.pepper_version,
                employee.is_active,
            ),
        )

    def update_credentials(
        self,
        employee_id: EmployeeId,
        *,
        pin_hash: str | None = None,
        password_hash: str | None = None,
        pepper_version: int | None = None,
    ) -> None:
        """Sirrləri AYRICA yeniləyir — `None` verilən sahə TOXUNULMUR.

        `COALESCE` ilə: yalnız açıq verilən dəyər yazılır, qalanı olduğu kimi
        qalır. Bu, "PIN-i yenilədim, təsadüfən şifrəni sıfırladım" səhvini
        struktur olaraq bağlayır.
        """
        self._execute(
            """
            UPDATE employees SET
                pin_hash       = COALESCE(%s, pin_hash),
                password_hash  = COALESCE(%s, password_hash),
                pepper_version = COALESCE(%s, pepper_version)
            WHERE id = %s AND tenant_id = %s
            """,
            (pin_hash, password_hash, pepper_version, employee_id, self._tenant),
        )

    # ------------------------ CredentialWriter portu ------------------------- #
    #
    # `user_management.CredentialWriter` üç metod tələb edir və kompozisiya kökü
    # ONU MƏHZ BU SİNFƏ BAĞLAYIR (`composition.py`: `credentials=uow.employees`).
    # Metodlar isə YOX İDİ — `uow.employees` `Any` qaytardığı üçün nə mypy, nə
    # də hər hansı test bunu tuta bilmirdi; `[Şifrəni Yenilə]` düyməsi istehsalat
    # yolunda `AttributeError` ilə çökürdü. Aşağıdakı üç metod həmin protokolu
    # ödəyir və YENİ yazma yolu icad ETMİR: hər üçü mövcud `update_credentials()`
    # / `save()` SQL-inə yönləndirir.

    def set_password(
        self, employee_id: EmployeeId, *, raw_password: str, must_change: bool
    ) -> None:
        """Xam şifrəni heşləyib yazır (`CredentialWriter`).

        HEŞLƏMƏ BURADA OLUR, USE CASE-də YOX: use case xam şifrəni alır və
        `Employee` entity-si heşi SAXLAMIR (bax `CredentialWriter` başlığı) —
        yəni heş ilə sətir arasında yeganə keçid nöqtəsi budur.

        `must_change` sütununu `save()` yazır (entity sahəsidir), lakin bu axın
        `save()` çağırılmadan da düzgün nəticə verməlidir — ona görə bayraq
        BURADA da açıq şəkildə yazılır. İki yazı bir-birini ÜST-ÜSTƏ təsdiqləyir,
        ziddiyyət yaratmır: hər ikisi eyni dəyəri qoyur.
        """
        hashing = self._hashing()
        self.update_credentials(
            employee_id,
            password_hash=hashing.hash_password(raw_password),
            pepper_version=hashing.current_pepper_version,
        )
        self._execute(
            "UPDATE employees SET must_change_password = %s WHERE id = %s AND tenant_id = %s",
            (must_change, employee_id, self._tenant),
        )

    def set_pin(self, employee_id: EmployeeId, *, raw_pin: str) -> None:
        """Xam PIN-i heşləyib yazır (`CredentialWriter`).

        PIN `employee_id`-yə bağlı heşlənir (SEC-005), ona görə heş sətirdən
        AYRI hesablana bilməz — identifikator burada onsuz da əldədir.
        """
        hashing = self._hashing()
        self.update_credentials(
            employee_id,
            pin_hash=hashing.hash_pin(raw_pin, employee_id=str(employee_id)),
            pepper_version=hashing.current_pepper_version,
        )

    def clear_pin_lockout(self, employee_id: EmployeeId) -> None:
        """Lockout sayğacını sıfırlayır (`CredentialWriter`).

        YENİ PIN TƏK BAŞINA KİFAYƏT ETMİR: 5 səhv cəhddən sonra bloklanmış işçi
        yeni PIN-lə də 15 dəqiqə gözləməli olardı — yəni sıfırlama görünüşdə
        işləyər, praktikada işləməzdi (bax `UserManagementUseCase.reset_pin`).
        """
        self._execute(
            """
            UPDATE employees
               SET pin_failed_attempts = 0, pin_locked_until = NULL
             WHERE id = %s AND tenant_id = %s
            """,
            (employee_id, self._tenant),
        )

    def _hashing(self) -> Any:
        """Argon2id servisi — ROOT şifrə siyasəti (`PASSWORD_MIN_LENGTH`) ilə.

        HƏR ÇAĞIRIŞDA YENİDƏN QURULUR və bu qəsdəndir: `InfrastructureLimits`
        vəziyyət saxlamır, lakin servisin özü uzun ömürlü olsaydı Root-un
        siyasət dəyişikliyi yalnız prosesin yenidən başladılmasından sonra
        qüvvəyə minərdi. Qurulma qiyməti Argon2 heşinin özündən qat-qat
        ucuzdur, yəni qənaət etməyə dəyməz.

        Limit pəncərəsi EYNİ BAĞLANTIDAN qurulur (`self._conn`): sirr yazısı
        ilə siyasət oxusu bir tranzaksiyada qalır, əks halda ikinci bağlantı
        RLS konteksti olmadan boş nəticə qaytarardı (SEC-008).

        İdxallar YEREL: `config_repositories` bu modulun `_BaseRepository`-sini
        idxal edir — modul səviyyəsində yazılsaydı dövrə yaranardı.
        """
        from src.infrastructure.config.limits import InfrastructureLimits  # noqa: PLC0415
        from src.infrastructure.persistence.config_repositories import (  # noqa: PLC0415
            PostgresSystemLimits,
        )
        from src.infrastructure.security.hashing import HashingService  # noqa: PLC0415

        return HashingService(
            limits=InfrastructureLimits(
                limits=PostgresSystemLimits(self._conn, self._context),
                tenant_id=self._tenant,
            )
        )

    def rename_username(self, employee_id: EmployeeId, username: Username) -> None:
        """Giriş identifikatorunu dəyişir — AYRICA əməliyyat.

        `save()`-dən qəsdən ayrılıb: giriş adının dəyişməsi istifadəçinin
        sistemə girə bilməməsi ilə nəticələnə bilər, ona görə profil
        redaktəsinin yan təsiri kimi baş verməməlidir.
        """
        self._execute(
            "UPDATE employees SET username = %s WHERE id = %s AND tenant_id = %s",
            (str(username), employee_id, self._tenant),
        )

    # ------------------------------ köməkçi --------------------------------- #

    def _sync_overrides(self, employee: Employee) -> None:
        codes = [o.flag_code for o in employee.overrides]
        self._execute(
            "DELETE FROM user_permission_overrides WHERE user_id = %s AND flag_code <> ALL(%s)",
            (employee.id, codes or [""]),
        )
        for override in employee.overrides:
            self._execute(
                """
                INSERT INTO user_permission_overrides
                    (user_id, flag_code, effect, granted_by, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, flag_code) DO UPDATE SET
                    effect     = EXCLUDED.effect,
                    granted_by = EXCLUDED.granted_by,
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    employee.id,
                    override.flag_code,
                    override.effect.value,
                    override.granted_by,
                    override.expires_at,
                ),
            )

    def _sync_store_assignments(self, employee: Employee) -> None:
        assigned = list(employee.assigned_store_ids)
        if not assigned:
            self._execute(
                "DELETE FROM camera_operator_store_assignment WHERE operator_id = %s",
                (employee.id,),
            )
            return
        self._execute(
            """
            DELETE FROM camera_operator_store_assignment
            WHERE operator_id = %s AND store_id <> ALL(%s)
            """,
            (employee.id, assigned),
        )
        for store_id in assigned:
            self._execute(
                """
                INSERT INTO camera_operator_store_assignment
                    (operator_id, store_id, assigned_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (operator_id, store_id) DO NOTHING
                """,
                (employee.id, store_id, self._context.user_id or employee.id),
            )

    def _hydrate(self, row: dict[str, Any]) -> Employee:
        position_row = self._fetch_one(
            """
            SELECT id, tenant_id, code, name_az, priority, is_system,
                   is_camera_type, is_store_tier, is_active
            FROM positions WHERE id = %s
            """,
            (row["position_id"],),
        )
        if position_row is None:  # pragma: no cover - FK bunu qoruyur
            msg = f"Rol tapılmadı: {row['position_id']}"
            raise LookupError(msg)

        position = position_from_row(position_row)
        flags = self._fetch_all(
            "SELECT flag_code FROM position_permissions WHERE position_id = %s AND granted",
            (position.id,),
        )
        apply_position_flags(position, [f["flag_code"] for f in flags])

        employee = employee_from_row(row, position)

        overrides = self._fetch_all(
            """
            SELECT flag_code, effect, granted_by, expires_at
            FROM user_permission_overrides WHERE user_id = %s
            """,
            (employee.id,),
        )
        apply_overrides(employee, overrides)

        if position.is_camera_type or position.code == "KAMERA_NEZARETCISI":
            stores = self._fetch_all(
                "SELECT store_id FROM camera_operator_store_assignment WHERE operator_id = %s",
                (employee.id,),
            )
            apply_store_assignments(employee, [s["store_id"] for s in stores])

        employee.discard_events()
        return employee


# --------------------------------------------------------------------------- #
# LeaveRequest
# --------------------------------------------------------------------------- #


#: İkinci təsdiq gözləyən vaxt düzəlişlərinin süzgəci (M-5).
#:
#: MODUL SƏVİYYƏSİNDƏ SABİTDİR — `_EXPORTABLE_FINES_WHERE` ilə eyni naxış:
#: mətndə istifadəçi girişi YOXDUR, yeganə dəyişən (`tenant_id`) `%s` ilə
#: parametrləşdirilib. `S608` direktivi FRAQMENTDƏ deyil, birləşmə sətrindədir
#: — ruff yalnız orada tam sorğu görür (RUF100 istifadəsiz direktivi rədd edir).
_PENDING_DUAL_CONTROL_WHERE: Final = """
    WHERE tenant_id = %s
      AND (SELECT o.status
             FROM manual_time_overrides o
            WHERE o.leave_request_id = leave_requests.id
            ORDER BY o.created_at DESC
            LIMIT 1) = 'PENDING_DUAL_CONTROL'
    ORDER BY requested_time
"""


class PostgresLeaveRequestRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, employee_id, store_id, leave_type_id,
               requested_time, requested_ntp_verified, return_claimed_time,
               actual_return_time, verified_at, verified_by, status,
               requested_minutes, delay_minutes, total_minutes,
               was_manual_override, escalated_at
        FROM leave_requests
    """

    _OPEN_STATUSES = (
        LeaveStatus.OUTSIDE.value,
        LeaveStatus.PENDING_RETURN_VERIFICATION.value,
        LeaveStatus.TIMEOUT_ESCALATED.value,
    )

    def get(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (request_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def get_for_update(self, request_id: LeaveRequestId) -> LeaveRequest | None:
        """`get()`-in SƏTİR KİLİDLİ variantı — YALNIZ yazma axını üçün.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `get()` DƏYİŞDİRİLMİR
        ──────────────────────────────────────────────────────────────────────
        `get()` ekranlarda, hesabatlarda və növbə baxışlarında da işlədilir.
        Ona `FOR UPDATE` qoymaq hər sadə baxışı yazı-kilidinə çevirər və
        paralel oxuları bir-birinə gözlədərdi. Ona görə kilidli variant AYRICA
        metoddur; onu yalnız STEP 3 / override / dual-control axını çağırır.

        Kilid TRANZAKSİYA sonuna qədər saxlanılır. Bu, layihənin "uzun-ömürlü
        tranzaksiya QADAĞANDIR" qaydası ilə ziddiyyət təşkil ETMİR: kontroller
        naxışı (CLAUDE.md §6) hər əməliyyat üçün ayrıca qısa sessiya açır —
        panel saatlarla açıq qalsa da tranzaksiya millisaniyələr yaşayır.

        `FOR UPDATE` sətri LOCK edir; `_hydrate` içindəki override oxusu isə
        kilidsizdir — override sətri append-only-dir və yarışın mövzusu deyil.
        """
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (request_id, self._tenant),
        )
        return self._hydrate(row) if row else None

    def find_open_for_employee_locked(self, employee_id: EmployeeId) -> LeaveRequest | None:
        """`find_open_for_employee`-nin SƏTİR KİLİDLİ variantı — YALNIZ `claim_return`
        (STEP 2, DOM-R2-02 audit tapıntısı, dövrə 2).

        `get_for_update`-lə EYNİ məntiq (bax onun şərhi: niyə `get()`/
        `find_open_for_employee` DƏYİŞDİRİLMİR, niyə kilid tranzaksiya sonuna
        qədər YAŞAYA BİLƏR) — YALNIZ `WHERE` şərti fərqlidir: ID YOX,
        "bu işçinin AÇIQ sorğusu" axtarılır. `_OPEN_STATUSES` `find_open_
        for_employee` ilə HƏRFƏN eynidir ki, kilidli variant kilidsiz
        variantın tapdığı EYNİ sətri versin.

        `FOR UPDATE` Postgres qrammatikasında `LIMIT`-dən SONRA yazılır
        (`ORDER BY ... LIMIT ... FOR UPDATE`) — sıra təsadüfi deyil, dil
        qaydasıdır.
        """
        row = self._fetch_one(
            self._SELECT
            + """
            WHERE employee_id = %s AND tenant_id = %s AND status = ANY(%s)
            ORDER BY requested_time DESC LIMIT 1 FOR UPDATE
            """,
            (employee_id, self._tenant, list(self._OPEN_STATUSES)),
        )
        return self._hydrate(row) if row else None

    def find_open_for_employee(self, employee_id: EmployeeId) -> LeaveRequest | None:
        row = self._fetch_one(
            self._SELECT
            + """
            WHERE employee_id = %s AND tenant_id = %s AND status = ANY(%s)
            ORDER BY requested_time DESC LIMIT 1
            """,
            (employee_id, self._tenant, list(self._OPEN_STATUSES)),
        )
        return self._hydrate(row) if row else None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[LeaveRequest]:
        """FAIL-SAFE: boş mağaza siyahısı → boş nəticə (bölmə 4)."""
        if not store_ids:
            return []
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND store_id = ANY(%s) AND status = %s
            ORDER BY return_claimed_time
            """,
            (
                self._tenant,
                list(store_ids),
                LeaveStatus.PENDING_RETURN_VERIFICATION.value,
            ),
        )
        return [self._hydrate(row) for row in rows]

    def list_due_for_timeout(
        self, tenant_id: TenantId, *, now: datetime, timeout_minutes: int
    ) -> list[LeaveRequest]:
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND status = %s AND escalated_at IS NULL
              AND return_claimed_time < %s - make_interval(mins => %s)
            """,
            (
                self._require_matching_tenant(tenant_id),
                LeaveStatus.PENDING_RETURN_VERIFICATION.value,
                now,
                timeout_minutes,
            ),
        )
        return [self._hydrate(row) for row in rows]

    def list_pending_dual_control(self, tenant_id: TenantId) -> list[LeaveRequest]:
        """İkinci təsdiq gözləyən vaxt düzəlişləri (M-5).

        ──────────────────────────────────────────────────────────────────────
        NİYƏ "SON SƏTİR" ALT-SORĞUSU, SADƏ `IN (...)` YOX
        ──────────────────────────────────────────────────────────────────────
        `manual_time_overrides` APPEND-ONLY-dir: təsdiq gələndə köhnə
        `PENDING_DUAL_CONTROL` sətri SİLİNMİR, üstünə `APPROVED` sətri
        yazılır (bax `_save_override`). Sadə `WHERE status = 'PENDING_DUAL_
        CONTROL'` süzgəci ona görə ARTIQ TƏSDİQLƏNMİŞ sorğuları da qaytarardı
        və planlaşdırılmış iş onları "müddəti bitdi" deyə ləğv etməyə
        çalışardı.

        Ona görə şərt `_hydrate`-in oxuduğu SƏTRƏ tətbiq olunur — yəni
        `ORDER BY created_at DESC LIMIT 1`. İki yer eyni sətri görməlidir,
        əks halda repo bir vəziyyət, entity başqa vəziyyət oxuyardı.
        """
        rows = self._fetch_all(
            self._SELECT + _PENDING_DUAL_CONTROL_WHERE,
            (self._require_matching_tenant(tenant_id),),
        )
        return [self._hydrate(row) for row in rows]

    def monthly_used_minutes(self, employee_id: EmployeeId, *, year: int, month: int) -> int:
        """Aylıq istifadə olunmuş icazə dəqiqələri (bölmə 3 limiti üçün).

        `total_minutes` sütunu cərimə düsturunun nəticəsidir (`allowance +
        2 × delay`) — yəni işçinin AYLIQ BÜDCƏDƏN faktiki yediyi vaxt.
        Aqreqasiya SQL-də edilir: bir ayın sorğularını yaddaşa gətirib
        Python-da toplamaq 21 filial üçün mənasız yük olardı.
        """
        row = self._fetch_one(
            """
            SELECT COALESCE(sum(total_minutes), 0) AS used
            FROM leave_requests
            WHERE employee_id = %s
              AND tenant_id = %s
              AND status = 'VERIFIED'
              AND date_part('year', requested_time) = %s
              AND date_part('month', requested_time) = %s
            """,
            (employee_id, self._tenant, year, month),
        )
        return int(row["used"]) if row else 0

    def save(self, request: LeaveRequest) -> None:
        params = leave_request_to_params(request)
        try:
            self._insert(params)
        except pg_errors.UniqueViolation as error:
            # ──────────────────────────────────────────────────────────────
            # STEP 1 TƏKRAR KLİKİ — XAM DB İSTİSNASI OLMAMALIDIR
            # ──────────────────────────────────────────────────────────────
            # Use case `find_open_for_employee()` ilə yoxlayır, lakin yoxlama
            # ilə INSERT arasında pəncərə var: iki paralel sorğu (və ya sadəcə
            # cüt klik) hər ikisi "açıq icazə yoxdur" görür. Yarışı DB udur —
            # `uq_leave_one_open_per_employee` ikincini rədd edir.
            #
            # Həmin rədd istifadəçiyə `UniqueViolation` kimi çatmamalıdır:
            # bu, texniki nasazlıq deyil, məhz use case-dəki İŞ QAYDASIDIR.
            # Ona görə MÖVCUD istisnaya (`OperationNotPermittedError`) və eyni
            # Azərbaycanca mesaja çevrilir — yeni istisna sinfi yaradılmır ki,
            # çağıran tərəflər (ekran, kiosk, plugin) tək bir hal tutsun.
            raise OperationNotPermittedError(
                "İşçinin artıq açıq icazə sorğusu var (DB unikal indeksi)",
                user_message="Sizin artıq açıq icazəniz var. Əvvəlcə qayıdışı təsdiqləyin.",
                context={
                    "request_id": str(request.id),
                    "employee_id": str(request.employee_id),
                    "constraint": getattr(error.diag, "constraint_name", None),
                },
            ) from error
        if request.override is not None:
            self._save_override(request)

    def _insert(self, params: dict[str, Any]) -> None:
        """`save()`-ın SQL gövdəsi — dəyişmədən köçürülüb (bax `save()`)."""
        self._execute(
            """
            INSERT INTO leave_requests
                (id, tenant_id, employee_id, store_id, leave_type_id,
                 requested_time, requested_ntp_verified, return_claimed_time,
                 actual_return_time, verified_at, verified_by, status,
                 requested_minutes, delay_minutes, total_minutes,
                 was_manual_override, escalated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                return_claimed_time = EXCLUDED.return_claimed_time,
                actual_return_time  = EXCLUDED.actual_return_time,
                verified_at         = EXCLUDED.verified_at,
                verified_by         = EXCLUDED.verified_by,
                status              = EXCLUDED.status,
                delay_minutes       = EXCLUDED.delay_minutes,
                total_minutes       = EXCLUDED.total_minutes,
                was_manual_override = EXCLUDED.was_manual_override,
                escalated_at        = EXCLUDED.escalated_at
            """,
            (
                params["id"],
                params["tenant_id"],
                params["employee_id"],
                params["store_id"],
                params["leave_type_id"],
                params["requested_time"],
                params["requested_ntp_verified"],
                params["return_claimed_time"],
                params["actual_return_time"],
                params["verified_at"],
                params["verified_by"],
                params["status"],
                params["requested_minutes"],
                params["delay_minutes"],
                params["total_minutes"],
                params["was_manual_override"],
                params["escalated_at"],
            ),
        )

    def _save_override(self, request: LeaveRequest) -> None:
        override = request.override
        assert override is not None
        # `REJECTED` HƏM insan rəddini, HƏM timeout ləğvini bildirir (M-5) —
        # ikisini `rejection_reason` mətni və `approved_by`-ın boşluğu ayırır.
        # `override_status` enum-una beşinci dəyər əlavə etmək RƏDD EDİLDİ:
        # `ALTER TYPE ... ADD VALUE` miqrasiyanı tranzaksiyadan kənara
        # çıxarardı, halbuki fərq onsuz da sətirdə görünür.
        if override.is_rejected:
            status = "REJECTED"
        elif override.is_pending_approval:
            status = "PENDING_DUAL_CONTROL"
        else:
            status = "APPROVED" if override.approved_by else "AUTO_APPROVED"
        # `approved_by` sütunu "İKİNCİ ŞƏXSİN kimliyi" mənasını daşıyır: təsdiq
        # sətrində təsdiqləyən, rədd sətrində rədd edən. `REJECTED` + `NULL`
        # isə "qərarı insan vermədi" (timeout) deməkdir — `chk_override_dual_
        # control` yalnız `APPROVED` üçün doluluq tələb edir, ona görə bu
        # istifadə mövcud məhdudiyyətlərə toxunmur. Ayrıca `rejected_by`
        # sütunu əlavə etmək RƏDD EDİLDİ: eyni suala ikinci sütun,
        # miqrasiya və iki mənbə riski.
        decided_by = override.rejected_by if override.is_rejected else override.approved_by
        self._execute(
            """
            INSERT INTO manual_time_overrides
                (tenant_id, leave_request_id, operator_id, employee_id,
                 system_time, overridden_time, delta_minutes, reason,
                 status, approved_by, approved_at, rejection_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request.tenant_id,
                request.id,
                override.operator_id,
                request.employee_id,
                override.system_time,
                override.overridden_time,
                override.delta_minutes,
                override.reason,
                status,
                decided_by,
                override.approved_at,
                override.rejection_reason,
            ),
        )

    def _hydrate(self, row: dict[str, Any]) -> LeaveRequest:
        override_row = self._fetch_one(
            """
            SELECT operator_id, system_time, overridden_time, reason,
                   delta_minutes, status, approved_by, approved_at,
                   rejection_reason, created_at
            FROM manual_time_overrides
            WHERE leave_request_id = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (row["id"],),
        )
        return leave_request_from_row(row, override_row)


# --------------------------------------------------------------------------- #
# AttendanceRecord
# --------------------------------------------------------------------------- #


class PostgresAttendanceRepository(_BaseRepository):
    _SELECT = """
        SELECT id, tenant_id, employee_id, store_id, work_date, check_in_status,
               requested_at, verified_at, verified_by, reject_reason, rejected_at,
               is_late, late_minutes, is_unauthorized_absence, ntp_verified,
               escalated_at, created_at
        FROM attendance_records
    """

    def get(self, record_id: AttendanceRecordId) -> AttendanceRecord | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s",
            (record_id, self._tenant),
        )
        return attendance_from_row(row) if row else None

    def get_for_day(self, employee_id: EmployeeId, work_date: date) -> AttendanceRecord | None:
        row = self._fetch_one(
            self._SELECT + " WHERE employee_id = %s AND work_date = %s AND tenant_id = %s",
            (employee_id, work_date, self._tenant),
        )
        return attendance_from_row(row) if row else None

    def get_for_day_for_update(
        self, employee_id: EmployeeId, work_date: date
    ) -> AttendanceRecord | None:
        """`get_for_day()`-in SƏTİR KİLİDLİ variantı — YALNIZ STEP C yazma axını.

        Oxu-yalnız yol (`employee_can_request_leave`, növbə siyahısı) kilidsiz
        qalır: orada kilid heç nə qorumur, yalnız paralel baxışları
        yavaşladardı. Kilid təsdiq/rədd yarışını bağlayır — bax
        `RowLockingAttendance` protokolunun izahı.
        """
        row = self._fetch_one(
            self._SELECT
            + " WHERE employee_id = %s AND work_date = %s AND tenant_id = %s FOR UPDATE",
            (employee_id, work_date, self._tenant),
        )
        return attendance_from_row(row) if row else None

    def list_pending_verification(self, store_ids: list[StoreId]) -> list[AttendanceRecord]:
        if not store_ids:
            return []
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE tenant_id = %s AND store_id = ANY(%s) AND check_in_status = %s
            ORDER BY requested_at
            """,
            (self._tenant, list(store_ids), CheckInStatus.PENDING_VERIFICATION.value),
        )
        return [attendance_from_row(row) for row in rows]

    def list_expected_on(self, tenant_id: TenantId, work_date: date) -> list[AttendanceRecord]:
        rows = self._fetch_all(
            self._SELECT + " WHERE tenant_id = %s AND work_date = %s",
            (self._require_matching_tenant(tenant_id), work_date),
        )
        return [attendance_from_row(row) for row in rows]

    def save(self, record: AttendanceRecord) -> None:
        params = attendance_to_params(record)
        self._execute(
            """
            INSERT INTO attendance_records
                (id, tenant_id, employee_id, store_id, work_date, check_in_status,
                 requested_at, verified_at, verified_by, reject_reason, rejected_at,
                 is_late, late_minutes, is_unauthorized_absence, ntp_verified,
                 escalated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_id, work_date) DO UPDATE SET
                check_in_status         = EXCLUDED.check_in_status,
                requested_at            = EXCLUDED.requested_at,
                verified_at             = EXCLUDED.verified_at,
                verified_by             = EXCLUDED.verified_by,
                reject_reason           = EXCLUDED.reject_reason,
                rejected_at             = EXCLUDED.rejected_at,
                is_late                 = EXCLUDED.is_late,
                late_minutes            = EXCLUDED.late_minutes,
                is_unauthorized_absence = EXCLUDED.is_unauthorized_absence,
                ntp_verified            = EXCLUDED.ntp_verified,
                escalated_at            = EXCLUDED.escalated_at
            """,
            (
                params["id"],
                params["tenant_id"],
                params["employee_id"],
                params["store_id"],
                params["work_date"],
                params["check_in_status"],
                params["requested_at"],
                params["verified_at"],
                params["verified_by"],
                params["reject_reason"],
                params["rejected_at"],
                params["is_late"],
                params["late_minutes"],
                params["is_unauthorized_absence"],
                params["ntp_verified"],
                params["escalated_at"],
            ),
        )


# --------------------------------------------------------------------------- #
# Fine
# --------------------------------------------------------------------------- #

#: Export-a düşə bilən statusların SQL literal siyahısı.
#:
#: MƏNBƏ DOMENDƏDİR — `Fine.EXPORTABLE_STATUSES`. Siyahı burada ƏL İLƏ
#: təkrar yazılsaydı, domendə `REDUCED` əlavə/çıxarıldıqda SQL sükutla köhnə
#: qalardı; məhz bu cür sürüşmə `list_exportable`-ı miqrasiya 003-dən sonra
#: iki il köhnə saxlamışdı. `sorted(...)` determinizm üçündür: dəst
#: (`frozenset`) sırasızdır, sorğu mətni isə hər proses başlanğıcında EYNİ
#: olmalıdır (plan keşi və diff oxunaqlığı).
_EXPORTABLE_STATUS_LITERALS: Final = ", ".join(
    f"'{status.value}'" for status in sorted(EXPORTABLE_STATUSES, key=lambda s: s.value)
)

#: `Fine.is_exportable`-in SQL qarşılığı (bölmə 6 LOCK MEXANİZMİ).
#:
#: DİNAMİK QURULMA — CLAUDE.md §4-ün "şərtlər SABİT sətir siyahısından qurulur"
#: istisnası. Dəyərlər istifadəçi girişi DEYİL, `FineStatus` enum-unun
#: üzvləridir. `%s` placeholder-i ilə ötürülsəydi `status IN (...)` şərti
#: `idx_fines_export_ready` QİSMƏN indeksinin predikatı ilə mətn olaraq
#: uyğunlaşmaz və planlaşdırıcı indeksi seçə bilməzdi.
#:
#: `S608` susdurma direktivi YOXDUR, çünki ruff bu fraqmenti işarələmir
#: (fraqmentdə `SELECT`/`FROM` yoxdur) — RUF100 istifadəsiz direktivi rədd edir.
#: Digər `%s` parametrləri (tenant və vaxt) əvvəlki kimi parametrləşdirilib.
#: `Fine.has_open_appeal`-in SQL mənbəyi — TÖRƏMƏ SÜTUN, saxlanılan sahə YOX
#: (bax `Fine.__init__` şərhi: iki mənbə saxlamaq sürüşmə riski yaradardı).
#:
#: `PENDING` VƏ `EXPIRED` birlikdə: birincisi "hələ baxılmayıb", ikincisi
#: "72 saat keçdi, yenə baxılmayıb". Hər ikisi QƏRARSIZDIR, yəni cərimə
#: mübahisəlidir (M-6). `APPROVED`/`REJECTED` isə qərardır və kilidi açır.
_UNDECIDED_APPEAL_EXISTS: Final = (
    " EXISTS (SELECT 1 FROM fine_appeals fa"
    "         WHERE fa.fine_id = fines.id"
    "           AND fa.status IN ('PENDING', 'EXPIRED'))"
)

#: `PENDING_REVIEW` statusunun SQL literalı — Aylıq Cərimə İcmalı sorğuları.
#:
#: `%s` PARAMETRİ DEYİL VƏ SƏBƏBİ `_EXPORTABLE_STATUS_LITERALS` ilə EYNİDİR:
#: `idx_fines_pending_review` QİSMƏN indeksdir
#: (`WHERE status = 'PENDING_REVIEW'`, miqrasiya 003) və planlaşdırıcı qismən
#: indeksi yalnız sorğu şərtinin onun predikatını SÜBUT ETDİYİ halda seçir.
#: Parametrləşdirilmiş `status = $1` bunu sübut etmir — icmal sorğusu 21
#: filialın bütün cərimələri üzərində tam skana düşərdi.
#:
#: Dəyər `FineStatus` enum-undan GÖTÜRÜLÜR, əl ilə yazılmır: status adı
#: dəyişsə sorğu sükutla boş nəticə qaytarardı (məhz `list_exportable`-ın
#: miqrasiya 003-dən sonra düşdüyü vəziyyət).
_PENDING_REVIEW_LITERAL: Final = f"'{FineStatus.PENDING_REVIEW.value}'"

_EXPORTABLE_FINES_WHERE: Final = (
    " WHERE tenant_id = %s"
    f" AND status IN ({_EXPORTABLE_STATUS_LITERALS})"
    " AND published_at IS NOT NULL"
    " AND appeal_window_closes_at IS NOT NULL"
    " AND appeal_window_closes_at <= %s"
    " AND exported_period IS NULL"
    # DÖRDÜNCÜ ŞƏRT (M-6) — `Fine.is_exportable` ilə birebir. Domendə
    # `has_open_appeal`, burada `NOT EXISTS`: eyni qayda iki qatda, CLAUDE.md
    # §5 tələbi. Yalnız birində olsaydı, ekranı yan keçən export skripti
    # mübahisəli cəriməni yenə tutardı.
    f" AND NOT {_UNDECIDED_APPEAL_EXISTS}"
    " ORDER BY fine_date"
)


class PostgresFineRepository(_BaseRepository):
    # `published_at`/`reviewed_by`/`review_decision_reason` (miqrasiya 003)
    # SİYAHIYA ƏLAVƏ EDİLİB: `fine_from_row` onları onsuz da oxumağa hazırdır
    # (`row.get(...)`), lakin sorğu onları gətirmədiyi üçün nəşr olunmuş cərimə
    # yaddaşa `published_at = None` ilə qayıdırdı — yəni 72 saatlıq pəncərənin
    # açılış anı hər oxunuşda İTİRDİ və `is_appeal_window_open()` həmişə `True`
    # deyirdi (export əbədi bloklanardı, bölmə 6).
    _SELECT = f"""
        SELECT id, tenant_id, employee_id, store_id, source, fine_type_id,
               leave_request_id, amount, fine_date, issued_by, photo_evidence_url,
               status, published_at, reviewed_by, review_decision_reason,
               reversed_by, reversed_at, reversal_reason,
               appeal_window_closes_at, exported_period, review_batch_id,
               idempotency_key, created_at AS issued_at,
               {_UNDECIDED_APPEAL_EXISTS} AS has_open_appeal
        FROM fines
    """  # noqa: S608 — fraqment SABİT sətirdir, istifadəçi girişi yoxdur

    def get_by_idempotency_key(self, tenant_id: TenantId, key: UUID) -> Fine | None:
        """D7: `DuplicateFineSubmissionError` tutulduqdan SONRA mövcud sətri tapır.

        `tenant_id` DEYİL, `self._tenant` işlədilir — INFRA-2 naxışı
        (RLS-ə əlavə ikinci qat, arqumentə güvənmə).
        """
        del tenant_id
        row = self._fetch_one(
            self._SELECT + " WHERE tenant_id = %s AND idempotency_key = %s",
            (self._tenant, key),
        )
        return fine_from_row(row) if row else None

    def get(self, fine_id: FineId) -> Fine | None:
        row = self._fetch_one(
            self._SELECT + " WHERE id = %s AND tenant_id = %s", (fine_id, self._tenant)
        )
        return fine_from_row(row) if row else None

    def unsynced_evidence_ids(self, fine_ids: Sequence[FineId]) -> set[FineId]:
        """`FineEvidenceSyncReader` portunu ödəyir (T3, `fine_review.py`).

        MƏNBƏ SÜTUNU `evidence_upload_status`-dur (miqrasiya 002), `photo_
        evidence_url` DEYİL — sonuncu MANUAL_CAMERA axınında LOKAL növbə
        açarını saxlayır, "dolu" olması Drive-a yükləndiyini SÜBUT ETMİR
        (port docstring-inin izah etdiyi qarışıqlıq). `source = 'MANUAL_
        CAMERA'` süzgəci QƏSDƏN BURADA YOXDUR — bu, biznes qaydasıdır və
        `MonthlyFineReviewUseCase._unsynced_evidence`-də qalır, əks halda
        qayda İKİ yerdə yaşayardı (CLAUDE.md §5-in TƏRSİNƏ pozuntusu: burada
        BİR qaydanın İKİ nüsxəsi yox, YERİ SƏHV olardı).

        TƏK sorğu (`id = ANY(%s)`) — aylıq icmalda yüzlərlə sətir ola bilər,
        N+1 qadağandır (`docs/performance_notes.md`).
        """
        rows = self._fetch_all(
            """
            SELECT id FROM fines
             WHERE tenant_id = %s AND id = ANY(%s) AND evidence_upload_status <> 'SYNCED'
            """,
            (self._tenant, list(fine_ids)),
        )
        return {FineId(row["id"]) for row in rows}

    def list_for_employee_month(
        self, employee_id: EmployeeId, *, year: int, month: int
    ) -> list[Fine]:
        """ "Cərimələrim" görünüşü (`ManualFineUseCase.my_fines`, bölmə 3).

        D3 (dövrə audit): AY SÜZGƏCİ TƏK ŞƏRT DEYİL. Cərimə avqustda
        `fine_date` ilə yazılır (`PENDING_REVIEW`), aylıq icmaldan sonra
        SENTYABRDA `publish()` olunur — 72 saatlıq etiraz pəncərəsi məhz O
        AN başlayır (`Fine.publish()`). Yalnız ay şərti saxlanılsaydı, işçi
        sentyabrda "Cərimələrim"i açanda avqust `fine_date`-li cərimə
        görünmür → boş siyahı, etiraz hüququ heç açılmadan bağlanır (hüquqi
        risk — `list_exportable`-ın başlığındakı EYNİ qeydin güzgüsü, orada
        artıq düzəldilib).

        İKİNCİ ŞƏRT `list_exportable`-ın (§6 LOCK MEXANİZMİ) `Fine.
        is_appeal_window_open` ilə eyni məntiqidir: nəşr olunub VƏ pəncərə
        HƏLƏ bağlanmayıb. `now()` Postgres-in server vaxtıdır — bölmə 4
        `Clock` qaydası DOMEN koduna aiddir (`require_aware`,
        determinstik test), bu isə SADƏ OXU FİLTRİDİR və `list_for_employee_
        month`-un Protocol imzası (`ports.py`, domen sahəsi) `now`
        parametri DAŞIMIR — imzanı dəyişmədən DÜZGÜN nəticəni server
        vaxtından almaq YEGANƏ yoldur.

        Ay süzgəci ATILMIR (kart «bu ay» semantikasını saxlayır) — açıq
        pəncərə şərti ƏLAVƏ (`OR`) kimi qoşulur.
        """
        rows = self._fetch_all(
            self._SELECT
            + """
            WHERE employee_id = %s AND tenant_id = %s
              AND (
                (EXTRACT(YEAR FROM fine_date) = %s AND EXTRACT(MONTH FROM fine_date) = %s)
                OR (published_at IS NOT NULL
                    AND appeal_window_closes_at IS NOT NULL
                    AND appeal_window_closes_at > now())
              )
            ORDER BY fine_date DESC
            """,
            (employee_id, self._tenant, year, month),
        )
        return [fine_from_row(row) for row in rows]

    def list_exportable(self, tenant_id: TenantId, *, now: datetime) -> list[Fine]:
        """Bölmə 6 LOCK MEXANİZMİ — `Fine.is_exportable` ilə TAM eyni şərt.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ `status <> 'REVERSED'` KİFAYƏT DEYİLDİ
        ──────────────────────────────────────────────────────────────────────
        Bu sorğu miqrasiya 003-dən ƏVVƏLKİ status modelində yazılmışdı: o
        vaxt cərimə `ACTIVE` doğulurdu və "ləğv olunmayıb" ilə "işçiyə
        görünür" EYNİ şey idi. 003 iki mərhələli görünmə gətirdi
        (`PENDING_REVIEW` → aylıq icmal → `PUBLISHED`, CLAUDE.md bölmə 9) və
        `v_exportable_fines` görünüşü həmin miqrasiyada yeniləndi — bu sorğu
        isə YENİLƏNMƏDİ. Nəticədə hələ icmaldan keçməmiş cərimə, `fine_date`
        üstündən 72 saat keçən kimi maaş export siyahısına düşə bilirdi:
        işçi onu NƏ GÖRÜB, NƏ də etiraz hüququ alıb (bölmə 6, hüquqi risk).

        İndi üç şərt də domendəki `Fine.is_exportable` ilə birebirdir:
        status `EXPORTABLE_STATUSES`-dədir, etiraz pəncərəsi bağlanıb,
        əvvəllər export olunmayıb.

        `published_at IS NOT NULL` ƏLAVƏ ŞƏRT KİMİ: `chk_fine_published`
        onsuz da tələb edir, lakin sorğunun özü də oxunanda "nəşr olunmuş"
        anlayışını açıq göstərməlidir — filtr statusdan asılı gizli
        fərziyyəyə söykənməsin.
        """
        # SAAS-1 (birinci partiya): sorğu arqumentin ÖZÜNÜ yox, bağlantının
        # kontekstini işlədir — uyğunsuzluq sükutla "boş siyahı" yox, açıq
        # xəta verir (bax `_require_matching_tenant`).
        rows = self._fetch_all(
            self._SELECT + _EXPORTABLE_FINES_WHERE,
            (self._require_matching_tenant(tenant_id), now),
        )
        return [fine_from_row(row) for row in rows]

    def list_in_range(self, tenant_id: TenantId, *, start: date, end: date) -> list[Fine]:
        """`RangeScopedFineReader` — aralığa düşən BÜTÜN cərimələr (Faza 8).

        NİYƏ HEÇ BİR LOCK ŞƏRTİ YOXDUR: əsaslandırma tam olaraq
        `domain/interfaces/ports.py::RangeScopedFineReader` başlığındadır —
        üç kateqoriyanın (tutulan / təxirə salınan / artıq tutulmuş) hər üçü
        hesablana bilsin deyə. Qərarı `Fine.is_exportable(now=...)` verir,
        bu sorğu YALNIZ namizədləri gətirir.

        `fine_date` üzrə süzülür (yazılma anı `created_at` YOX): gecikmiş
        yazılan cərimə hadisənin baş verdiyi dövrə düşməlidir, əks halda
        aralıqların sərhədində cərimə bir dövrdən digərinə sükutla sürüşərdi.

        `status` süzgəci də yoxdur — `PENDING_REVIEW` sətri `Fine.is_
        exportable()` tərəfindən onsuz da rədd edilir və onu SQL-də kəsmək
        həmin qərarı iki yerə yayardı.
        """
        rows = self._fetch_all(
            self._SELECT
            + " WHERE tenant_id = %s AND fine_date BETWEEN %s AND %s ORDER BY fine_date",
            (self._require_matching_tenant(tenant_id), start, end),
        )
        return [fine_from_row(row) for row in rows]

    # ------------------------- Aylıq Cərimə İcmalı --------------------------- #
    #
    # NİYƏ AYRICA METOD — `list_in_range` KİFAYƏT ETMİRDİ
    # ────────────────────────────────────────────────────────────────────────
    # `list_in_range`-də status süzgəci QƏSDƏN yoxdur (bax onun docstring-i):
    # export namizədləri üç kateqoriyaya bölünə bilsin deyə qərarı domen
    # verir. İcmal ekranında isə status SEÇİM MEYARIDIR — `PENDING_REVIEW`
    # olmayan sətir üzərində verilə biləcək qərar yoxdur (`publish_batch` onu
    # onsuz da süzür) və 21 filialın bir aylıq BÜTÜN cərimələrini yaddaşa
    # gətirib orada atmaq həmin ekranı ən çox sətri olan aylarda yavaşladardı.

    def list_pending_review(self, tenant_id: TenantId, *, year: int, month: int) -> list[Fine]:
        """Bir ayın nəşr gözləyən cərimələri — Aylıq Cərimə İcmalının siyahısı.

        `fine_date` üzrə süzülür, yazılma anı (`created_at`) üzrə YOX —
        `list_in_range` ilə eyni əsaslandırma: gecikmiş yazılan cərimə
        hadisənin baş verdiyi dövrün icmalında görünməlidir. Əks halda o, heç
        bir icmala düşməz və `PENDING_REVIEW` olaraq əbədi qalardı, yəni
        işçiyə nə görünər, nə də export-a düşərdi.

        ARALIQ ŞƏRTİ (`>= start AND < next_month`) `EXTRACT(...)`-dan
        SEÇİLİB: sonuncu sütun üzərində funksiya çağırışıdır və
        `idx_fines_pending_review` indeksini yararsız edərdi.

        Sıra `store_id`-dəndir, çünki ekran filiallara görə qruplaşdırır —
        sıralamanı SQL-də etmək qrupları tək keçidlə qurmağa imkan verir.
        """
        start = date(year, month, 1)
        # Növbəti ayın birinci günü — dekabrda il artır. `timedelta(days=31)`
        # işlətmək fevralda növbəti ayı ATLAYARDI.
        end = date(year + (month // 12), (month % 12) + 1, 1)
        rows = self._fetch_all(
            self._SELECT
            + f"""
            WHERE tenant_id = %s
              AND status = {_PENDING_REVIEW_LITERAL}
              AND fine_date >= %s AND fine_date < %s
            ORDER BY store_id, fine_date
            """,
            (self._require_matching_tenant(tenant_id), start, end),
        )
        return [fine_from_row(row) for row in rows]

    def pending_review_periods(self, tenant_id: TenantId) -> list[str]:
        """Nəşr gözləyən cəriməsi olan aylar (`YYYY-MM`), ARTAN sıra ilə.

        Ekranın dövr seçimi bunu işlədir və defolt olaraq ƏN KÖHNƏ dövrü
        açır: nəşr gecikdikdə işçinin etiraz pəncərəsi də gecikir, ona görə
        gözləyən ən qədim ay birinci görünməlidir.

        `to_char` NƏTİCƏDƏDİR, süzgəcdə YOX — süzgəc yalnız statusdadır və
        qismən indeksdən istifadə edir. Sıralama `YYYY-MM` mətninin özündən
        gedir: bu format leksikoqrafik olaraq xronoloji sıra ilə eynidir.
        """
        rows = self._fetch_all(
            f"""
            SELECT DISTINCT to_char(fine_date, 'YYYY-MM') AS period
              FROM fines
             WHERE tenant_id = %s AND status = {_PENDING_REVIEW_LITERAL}
             ORDER BY period
            """,  # noqa: S608 — status literalı enum-dan gəlir, bax `_PENDING_REVIEW_LITERAL`
            (self._require_matching_tenant(tenant_id),),
        )
        return [str(row["period"]) for row in rows]

    # -------------------------- Drive sübut sütunları ------------------------ #
    #
    # NİYƏ BUNLAR `save()`-dan KEÇMİR
    # ────────────────────────────────────────────────────────────────────────
    # `evidence_drive_*` sütunları (miqrasiya 002) cərimə YARADILAN anda hələ
    # məlum deyil — şəkil arxa planda yüklənir. Onları `Fine` entity-sinə
    # əlavə etmək domenə "yüklənmə vəziyyəti" anlayışı gətirərdi, halbuki bu,
    # tamamilə infrastruktur detalıdır: domen üçün sübut VAR, harada
    # saxlandığı isə onun qərarı deyil. Ona görə iki hədəfli UPDATE.

    def mark_evidence_pending(self, fine_id: FineId) -> None:
        """Şəkil növbəyə düşdü — `idx_fines_evidence_pending` bunu görür."""
        self._execute(
            """UPDATE fines SET evidence_upload_status = 'PENDING'
                WHERE id = %s AND tenant_id = %s""",
            (fine_id, self._tenant),
        )

    def attach_drive_evidence(
        self, fine_id: FineId, *, file_id: str, connection_id: UUID | None
    ) -> None:
        """Yükləmə bitdi — istinad sətrə yazılır.

        `photo_evidence_url` ÜZƏRİNDƏN YAZILMIR: orada növbə açarı qalır və
        o, hansı lokal yükləmənin bu sətri doldurduğunu göstərən yeganə izdir
        (miqrasiya 002 başlığı: sütun məhz buna görə silinmir).
        """
        self._execute(
            """UPDATE fines
                  SET evidence_drive_file_id = %s,
                      evidence_drive_connection_id = %s,
                      evidence_upload_status = 'SYNCED'
                WHERE id = %s AND tenant_id = %s""",
            (file_id, connection_id, fine_id, self._tenant),
        )

    def save(self, fine: Fine) -> None:
        # İCMAL SÜTUNLARI (`published_at`, `reviewed_by`,
        # `review_decision_reason`) SİYAHIYA ƏLAVƏ EDİLİB
        # ────────────────────────────────────────────────────────────────────
        # `fine_to_params` onları çoxdan verirdi, INSERT isə götürmürdü.
        # Nəticə iki qüsur idi:
        #   (a) `publish()`-dan sonra `published_at` DB-yə düşmürdü, halbuki
        #       `chk_fine_published` (miqrasiya 003) PUBLISHED sətirdə onun
        #       dolu olmasını TƏLƏB edir — yazı CHECK pozuntusu ilə çökürdü;
        #   (b) Saga kompensasiyası cəriməni `discard_in_review()` ilə
        #       `REVERSED` edir və həmin sətir də eyni CHECK-ə dəyirdi.
        # Sütunlar ƏLAVƏ olunur, mövcud `ON CONFLICT (id) DO UPDATE` naxışı
        # OLDUĞU KİMİ QALIR — sadəcə yenilənən sahələrin siyahısı genişlənir.
        #
        # SEC-8: `review_batch_id` EYNİ SƏBƏBLƏ ƏLAVƏ OLUNUR — `fine_to_
        # params` onu artıq verir (bax mapper-in şərhi), lakin bu INSERT/
        # UPDATE onu HEÇ VAXT bazaya göndərmirdi: "bu cərimə hansı partiyada
        # nəşr olundu?" sualı yaddaşda cavablı, DB-də HƏMİŞƏ NULL qalırdı.
        #
        # D7: `idempotency_key` + `try/except UniqueViolation` — `Postgres
        # LeaveRequestRepository.save()`-dəki HƏRFİ naxış (bax onun şərhi).
        # Qismən unikal indeks (`uq_fines_manual_camera_idempotency_key`,
        # migrations/074) İKİNCİ manual cərimə göndərişini DB SƏVİYYƏSİNDƏ
        # rədd edir; xam `UniqueViolation` çağırana SIZMIR — `ManualFineUseCase.
        # issue()` `DuplicateFineSubmissionError`-u tutub mövcud sətri
        # `get_by_idempotency_key()` ilə tapır və "uğurlu" nəticə qaytarır.
        params = fine_to_params(fine)
        try:
            self._execute(
                """
                INSERT INTO fines
                    (id, tenant_id, employee_id, store_id, source, fine_type_id,
                     leave_request_id, amount, fine_date, issued_by,
                     photo_evidence_url, status, published_at, reviewed_by,
                     review_decision_reason, reversed_by, reversed_at,
                     reversal_reason, appeal_window_closes_at, exported_period,
                     review_batch_id, idempotency_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    amount                 = EXCLUDED.amount,
                    status                 = EXCLUDED.status,
                    published_at           = EXCLUDED.published_at,
                    reviewed_by            = EXCLUDED.reviewed_by,
                    review_decision_reason = EXCLUDED.review_decision_reason,
                    reversed_by            = EXCLUDED.reversed_by,
                    reversed_at            = EXCLUDED.reversed_at,
                    reversal_reason        = EXCLUDED.reversal_reason,
                    appeal_window_closes_at = EXCLUDED.appeal_window_closes_at,
                    exported_period        = EXCLUDED.exported_period,
                    review_batch_id        = EXCLUDED.review_batch_id,
                    idempotency_key        = EXCLUDED.idempotency_key
                """,
                (
                    params["id"],
                    params["tenant_id"],
                    params["employee_id"],
                    params["store_id"],
                    params["source"],
                    params["fine_type_id"],
                    params["leave_request_id"],
                    params["amount"],
                    params["fine_date"],
                    params["issued_by"],
                    params["photo_evidence_url"],
                    params["status"],
                    params["published_at"],
                    params["reviewed_by"],
                    params["review_decision_reason"],
                    params["reversed_by"],
                    params["reversed_at"],
                    params["reversal_reason"],
                    params["appeal_window_closes_at"],
                    params["exported_period"],
                    params["review_batch_id"],
                    params["idempotency_key"],
                ),
            )
        except pg_errors.UniqueViolation as error:
            # INF-01 (dövrə 1 audit): `fines`-də İKİ MÜSTƏQİL unikal indeks var
            # və onları EYNİ istisnaya yığmaq YANLIŞ diaqnoz qoyardı —
            # `constraint_name`-ə görə BUDAQLANIR, naməlum halda xam istisna
            # ötürülür (fail-loud, sükutla səhv izah uydurmaqdansa).
            constraint = getattr(error.diag, "constraint_name", None)
            if constraint == "uq_fines_manual_camera_idempotency_key":
                # D7: eyni forma İKİNCİ dəfə göndərilib (operatorun ÖZÜ ilə
                # yarış) — `ManualFineUseCase.issue()` bunu tutub mövcud
                # sətri `get_by_idempotency_key()` ilə tapır (bax onun şərhi).
                raise DuplicateFineSubmissionError(
                    "Eyni idempotentlik açarı ilə cərimə artıq mövcuddur (DB unikal indeksi)",
                    context={
                        "fine_id": str(fine.id),
                        "idempotency_key": str(fine.idempotency_key),
                        "constraint": constraint,
                    },
                ) from error
            if constraint == "uq_fines_one_live_auto_delay_per_leave":
                # İKİ FƏRQLİ Kamera Operatorunun EYNİ gecikməni EYNİ ANDA
                # təsdiqləməsi — yarış qapağıdır, idempotentlik DEYİL (bax
                # `ConcurrentVerificationConflictError` docstring-i). QƏSDƏN
                # BURADA TUTULMUR: sərbəst yuxarı sızmalıdır ki, Saga
                # (`LeaveVerificationUseCase.verify_return::step_create_fine`)
                # addımı UĞURSUZ sayıb kompensasiya etsin.
                raise ConcurrentVerificationConflictError(
                    "Bu icazə üçün cərimə artıq başqa təsdiq tərəfindən yaradılıb "
                    "(DB unikal indeksi)",
                    context={
                        "fine_id": str(fine.id),
                        "leave_request_id": (
                            str(fine.leave_request_id) if fine.leave_request_id else None
                        ),
                        "constraint": constraint,
                    },
                ) from error
            raise


class PostgresOpenFineExposureReader(_BaseRepository):
    """DEEP-GAP D2: `OpenFineExposureReader` portunu ödəyir (`user_management.py`).

    Ayrı sinif olması qəsdəndir (port başlığının izahı ilə eyni): sual
    YALNIZ deaktivasiya ön-yoxlamasına aiddir, `PostgresFineRepository`/
    `PostgresFineAppealRepository`-yə metod əlavə etsəydik hər ikisi bu dar
    ehtiyaca görə şişərdi.

    İKİ AYRI `COUNT` sorğusu — TƏK sorğuda `UNION`/alt-sorğu birləşdirmək
    mümkün olsa da, iki müstəqil ədəd (`OpenFineExposure`-un iki sahəsi)
    üçün oxunaqlılıq performans qazancından ÜSTÜNDÜR: bu, hər iş axınında
    DEYİL, YALNIZ işçi deaktiv edilərkən (nadir hadisə) bir dəfə çağırılır.
    """

    def count_open_for_employee(self, employee_id: EmployeeId) -> OpenFineExposure:
        pending_review = self._fetch_one(
            f"""
            SELECT COUNT(*) AS n FROM fines
             WHERE employee_id = %s AND tenant_id = %s AND status = {_PENDING_REVIEW_LITERAL}
            """,  # noqa: S608 — `_PENDING_REVIEW_LITERAL` sabit sətirdir, istifadəçi girişi yoxdur
            (employee_id, self._tenant),
        )
        # `_UNDECIDED_APPEAL_EXISTS`-in EYNİ status dəsti (`PENDING`, `EXPIRED`)
        # — `list_undecided`/`Fine.is_exportable`-in "qərarsız etiraz" tərifi
        # ilə birebir (M-6). `fine_appeals.employee_id` birbaşa sütundur,
        # `fines` üzərindən JOIN lazım deyil.
        open_appeals = self._fetch_one(
            """
            SELECT COUNT(*) AS n FROM fine_appeals
             WHERE employee_id = %s AND tenant_id = %s AND status IN ('PENDING', 'EXPIRED')
            """,
            (employee_id, self._tenant),
        )
        return OpenFineExposure(
            pending_review_fine_count=int(pending_review["n"]) if pending_review else 0,
            open_appeal_count=int(open_appeals["n"]) if open_appeals else 0,
        )


#: Bağlanmamış tapşırıq statusları — `TaskStatus.is_terminal`-in SQL güzgüsü.
#:
#: Dəyərlər enum-dan GÖTÜRÜLÜR, əl ilə yazılmır (`_EXPORTABLE_STATUS_LITERALS`
#: ilə eyni qərar): yeni status əlavə olunsa və ya adı dəyişsə, əl ilə yazılmış
#: siyahı sükutla köhnələr və işdən çıxma ekranı «tapşırıq yoxdur» göstərərdi.
#: `sorted(...)` determinizm üçündür — sorğu mətni hər başlanğıcda EYNİ olmalıdır.
_TERMINAL_TASK_LITERALS: Final = ", ".join(
    f"'{status.value}'"
    for status in sorted(TaskStatus, key=lambda status: status.value)
    if status.is_terminal
)


class PostgresOffboardingSignalReader(_BaseRepository):
    """HR-4: `OffboardingSignalReader` portunu ödəyir (`user_management.py`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BİR SORĞU
    ──────────────────────────────────────────────────────────────────────────
    Portun docstring-i bunu TƏLƏB EDİR: altı siqnal BİR siyahıda göstərilir və
    biri çatışmasa admin «hər şey təmizdir» oxuyar. Altı ayrı sorğu (və ya altı
    ayrı port) hər birinin ayrıca uğursuz ola biləcəyi ALTI yol yaradardı —
    tək sorğuda ya hamısı gəlir, ya da istisna qalxır.

    Bu, `PostgresOpenFineExposureReader`-in İKİ ayrı `COUNT` seçimi ilə
    ZİDDİYYƏT DEYİL: orada nəticə İKİ müstəqil ədəddir və hər ikisi eyni
    cədvəl ailəsindəndir (`fines`/`fine_appeals`); burada isə ALTI fərqli
    cədvəl var və natamamlıq riski məhz ondan doğur.

    Skalyar alt-sorğular `JOIN`-dan seçilib: hər siqnalın öz süzgəci var
    (status, tarix, `is_active`) və `JOIN` ilə yazsaydıq sətir çoxalması
    (fan-out) sayları şişirdərdi — məs. iki sənədi olan işçinin tapşırıqları
    ikiqat sayılardı.

    Kirayəçi şərti HƏR alt-sorğuda AYRICA yazılır (RLS-ə əlavə ikinci qat,
    `_BaseRepository` naxışı): bir alt-sorğuda unudulsa, həmin siqnal
    kirayəçilər arasında sızardı.
    """

    def read_offboarding_signals(self, employee_id: EmployeeId) -> OffboardingSignals:
        row = self._fetch_one(
            f"""
            SELECT
              (SELECT count(*) FROM leave_requests lr
                WHERE lr.employee_id = %s AND lr.tenant_id = %s
                  AND lr.status = ANY(%s))                       AS open_leave_requests,
              (SELECT count(*) FROM tasks t
                WHERE t.assignee_id = %s AND t.tenant_id = %s
                  AND t.status NOT IN ({_TERMINAL_TASK_LITERALS})) AS pending_tasks,
              (SELECT count(*) FROM open_shift_postings o
                WHERE o.claimed_by = %s AND o.tenant_id = %s
                  AND o.status = 'CLAIMED'
                  AND o.shift_date >= current_date)              AS upcoming_claimed_shifts,
              (SELECT COALESCE(
                        sum(GREATEST(b.entitled_days + b.carried_over_days - b.used_days, 0)),
                        0)
                 FROM annual_leave_balances b
                WHERE b.employee_id = %s AND b.tenant_id = %s
                  AND b.year = date_part('year', current_date))  AS unused_annual_leave_days,
              (SELECT count(*) FROM employee_documents d
                WHERE d.employee_id = %s AND d.tenant_id = %s
                  AND d.is_active
                  AND (d.expiry_date IS NULL OR d.expiry_date >= current_date))
                                                                 AS active_documents,
              (SELECT e.face_embedding IS NOT NULL FROM employees e
                WHERE e.id = %s AND e.tenant_id = %s)            AS has_face_template
            """,  # noqa: S608 — status literalları enum-dan gəlir, bax `_TERMINAL_TASK_LITERALS`
            (
                employee_id,
                self._tenant,
                # `_OPEN_STATUSES` ilə EYNİ dəst: «hələ xaricdə» tərifi bir
                # yerdə qalmalıdır, əks halda bu ekran icazəni açıq sayarkən
                # davamiyyət ekranı bağlanmış sayardı.
                list(PostgresLeaveRequestRepository._OPEN_STATUSES),
                employee_id,
                self._tenant,
                employee_id,
                self._tenant,
                employee_id,
                self._tenant,
                employee_id,
                self._tenant,
                employee_id,
                self._tenant,
            ),
        )
        if row is None:  # pragma: no cover - `SELECT` skalyarları həmişə sətir qaytarır
            return OffboardingSignals()
        return OffboardingSignals(
            open_leave_requests=int(row["open_leave_requests"] or 0),
            pending_tasks=int(row["pending_tasks"] or 0),
            upcoming_claimed_shifts=int(row["upcoming_claimed_shifts"] or 0),
            # `NUMERIC` sürücüdən `Decimal` kimi gəlir; `str()` üzərindən
            # keçirmək `float` yuvarlaqlaşdırmasının yolunu STRUKTUR olaraq
            # bağlayır — bu dəyər son haqq-hesabın girişidir (PUL).
            unused_annual_leave_days=Decimal(str(row["unused_annual_leave_days"] or 0)),
            active_documents=int(row["active_documents"] or 0),
            # İşçi sətri tapılmasa (`NULL`) cavab `False`-dur: «şablon var»
            # deyə YANLIŞ siqnal vermək, olmayan işçi üçün silinməli biometrik
            # məlumat axtarmağa aparardı.
            has_face_template=bool(row["has_face_template"]),
        )


__all__ = [
    "PostgresAttendanceRepository",
    "PostgresEmployeeRepository",
    "PostgresFineRepository",
    "PostgresLeaveRequestRepository",
    "PostgresOffboardingSignalReader",
    "PostgresOpenFineExposureReader",
    "PostgresPositionRepository",
]
