"""Face Control-un saxlama qatı (migrations/047) — `facecontrol.md` Faza 2.

Dörd repo bir faylda: `employees` sətrinin üz sahələri + arxiv, doğrulama
jurnalı, istisnalar və mağaza əhatəsi. Onlar birlikdə yaşayır, çünki EYNİ
tranzaksiyada işləyirlər (uyğunsuzluq sayğacı + jurnal sətri; yenidən-qeydiyyat
arxivi + yeni vektor) və ayrı fayllara bölmək "hansı iki yazı atomikdir?"
sualını iki başlığa parçalayardı.

QAYDA (bölmə 2): 100% parameterləşdirilmiş SQL. RLS-Ə ƏLAVƏ İKİNCİ QAT: hər
sorğuda açıq `tenant_id` şərti var — biometrik cədvəldə bu, adi izolyasiyadan
daha vacibdir.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏLƏMƏ MƏHZ BURADADIR — VƏ AAD İLƏ SƏTRƏ BAĞLANIR
──────────────────────────────────────────────────────────────────────────────
Vektor bazaya YALNIZ `EncryptionService` token-i kimi yazılır (mövcud modul,
AES-256-GCM; yeni şifrələmə kodu YAZILMIR). Şifrələmə use case-də deyil,
repo-da olur: əks halda tətbiq qatı infrastruktur sinfini birbaşa tanıyar və
"hansı sütun şifrəlidir?" qərarı iki qatda yaşayardı (`ErpServerRepository`
ilə eyni naxış).

`context=f"face_embedding:{employee_id}"` (AAD) QƏSDƏN VERİLİR və bu, bir
hücum yolunu bağlayır: bazaya yazma imkanı olan biri A işçisinin şifrəli
vektorunu B işçisinin sətrinə KÖÇÜRÜB B-nin PIN-i ilə A kimi görünə bilərdi.
AAD ilə həmin token B sətrində AÇILMIR — `DecryptionError` alınır və axın
fail-closed davranır (aşağıdakı `_decode_embedding` şərhinə bax).

──────────────────────────────────────────────────────────────────────────────
NİYƏ VEKTOR JSON MASSİVİ KİMİ SERİALLAŞDIRILIR
──────────────────────────────────────────────────────────────────────────────
`pickle` RƏDD EDİLDİ (şifrəni açan tərəf ixtiyari kod icra edə bilər — sətir
dəyişdirilə bilən bir mühitdə bu, uzaqdan kod icrasıdır), `struct`/xam bayt
isə ölçü/format sabitini koda hardcode edərdi (kitabxana versiyası vektor
ölçüsünü dəyişsə, köhnə sətirlər sükutla yanlış oxunardı). JSON massivi
özünü-təsvir edən, versiya-neytral və insan tərəfindən (açardan sonra) audit
edilə biləndir.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.domain.value_objects.face_recognition import (
    FaceEmbedding,
    FaceExemption,
    FaceExemptionStatus,
    FaceProfile,
    FaceStoreScope,
    FaceTriggerContext,
    FaceVerificationLogEntry,
    FaceVerificationResult,
    LivenessGesture,
)
from src.domain.value_objects.identifiers import (
    EmployeeId,
    FaceExemptionId,
    StoreId,
    TenantId,
)
from src.infrastructure.persistence.repositories import _BaseRepository
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import date, datetime

    from psycopg import Connection

    from src.infrastructure.persistence.connection import TenantContext
    from src.infrastructure.security.encryption import EncryptionService

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)


class PostgresFaceEmbeddingRepository(_BaseRepository):
    """`employees` üz sütunları + `face_embedding_history` arxivi.

    `delete()` YOXDUR: arxiv sətrindən `DELETE` hüququ miqrasiyada geri
    alınıb. Biometrik məzmunun silinməsi `UPDATE` ilə edilir (`status =
    'PURGED'`, vektor `NULL`) — yəni məlumat gedir, İZ qalır.
    """

    _PROFILE_SELECT = """
        SELECT id, tenant_id, store_id, face_embedding, face_enrolled_at,
               face_mismatch_attempts, face_locked_until
        FROM employees
    """

    def __init__(
        self,
        conn: Connection[dict[str, Any]],
        context: TenantContext,
        encryption: EncryptionService,
    ) -> None:
        """`encryption` DEFOLTSUZDUR — açıq ötürülməlidir.

        `EncryptionService()` defolt kimi qoyulsaydı, kompozisiya kökü onu
        ötürməyi unutsa belə repo işləyərdi (öz nüsxəsi ilə) və açar
        provayderinin fərqli qurulduğu bir mühitdə bu, sükutla açılmayan
        token-lər deməkdir. Məcburi arqument həmin səhvi işə salınma anına
        keçirir.
        """
        super().__init__(conn, context)
        self._encryption = encryption

    # -------------------------------- oxu ------------------------------------ #

    def list_unenrolled(self, tenant_id: TenantId, *, hired_before: date) -> list[Any]:
        """`UnenrolledEmployeeReader` — möhləti keçmiş, üzsüz işçilər (UX-7).

        ──────────────────────────────────────────────────────────────────────
        EYNİ SİNİF, İKİ PROTOKOL — MİRAS YOX (CLAUDE.md §3)
        ──────────────────────────────────────────────────────────────────────
        Sinif həm `FaceEmbeddingRepository`, həm `UnenrolledEmployeeReader`
        protokolunu STRUCTURAL ödəyir. Ayrı sinif yazmaq eyni `employees`
        cədvəlinə ikinci bir üz-oxuyucusu gətirərdi.

        ──────────────────────────────────────────────────────────────────────
        ÜÇ SÜZGƏC VƏ HƏR BİRİNİN SƏBƏBİ
        ──────────────────────────────────────────────────────────────────────
        * `is_active` — işdən çıxmış işçinin üzü qeydiyyata alınmır;
        * `store_id IS NOT NULL` — `exceptions.store_id` `NOT NULL`-dur və üz
          qapısı KİOSK qapısıdır (mərkəzi ofis işçisi kioskda giriş etmir);
        * `face_embedding IS NULL` — `PURGED` sətirdə vektor `NULL`-dur, yəni
          şablonu silinmiş işçi də «qeydiyyatsız» sayılır (doğrudur: onun
          kioskda girişi YENƏ mümkün deyil).

        `hire_date IS NULL` sətirlər QAYTARILMIR: möhlətin başlanğıc nöqtəsi
        məlum deyil və uydurma tarix ekranda YALAN son tarix göstərərdi (eyni
        qərar `FaceEnrollmentUseCase.enrollment_grace`-dədir).
        """
        from src.application.use_cases.face_control import (  # noqa: PLC0415
            UnenrolledEmployee,
        )

        rows = self._fetch_all(
            """
            SELECT id, store_id, first_name, last_name, hire_date
              FROM employees
             WHERE tenant_id = %s
               AND is_active = TRUE
               AND store_id IS NOT NULL
               AND face_embedding IS NULL
               AND hire_date IS NOT NULL
               AND hire_date < %s
             ORDER BY hire_date
            """,
            (self._require_matching_tenant(tenant_id), hired_before),
        )
        return [
            UnenrolledEmployee(
                employee_id=EmployeeId(row["id"]),
                store_id=StoreId(row["store_id"]),
                full_name=f"{row['first_name']} {row['last_name']}".strip(),
                hire_date=row["hire_date"],
            )
            for row in rows
        ]

    def get_profile(self, employee_id: EmployeeId) -> FaceProfile | None:
        row = self._fetch_one(
            f"{self._PROFILE_SELECT} WHERE id = %s AND tenant_id = %s",
            (employee_id, self._tenant),
        )
        return self._row_to_profile(row) if row else None

    def list_store_profiles(
        self, tenant_id: TenantId, store_id: StoreId, *, exclude: EmployeeId | None = None
    ) -> list[FaceProfile]:
        """MISMATCH cross-check dəsti — YALNIZ eyni mağaza, YALNIZ qeydiyyatlılar.

        `idx_employees_face_enrolled` qismən indeksi məhz bu sorğu üçün
        yaradılıb (`tenant_id, store_id` prefiksi + `WHERE face_embedding IS
        NOT NULL`).

        DEAKTİV İŞÇİLƏR KƏNARDADIR: onların vektoru onsuz da silinməlidir
        (bənd 8), lakin sətir hələ təmizlənməmiş ola bilər (məs. miqrasiyadan
        əvvəlki qeydlər) — belə halda kioskda duran adamın işdən çıxmış bir
        işçiyə "uyğun gəlməsi" HR-ə yanlış istiqamət verərdi.
        """
        clauses = [
            "tenant_id = %s",
            "store_id = %s",
            "is_active",
            "face_embedding IS NOT NULL",
        ]
        params: list[Any] = [tenant_id, store_id]
        if exclude is not None:
            clauses.append("id <> %s")
            params.append(exclude)

        # `clauses` SABİT sətir siyahısındandır — dəyərlər `%s` ilə bağlanır.
        rows = self._fetch_all(
            f"{self._PROFILE_SELECT} WHERE {' AND '.join(clauses)}",
            tuple(params),
        )
        return [self._row_to_profile(row) for row in rows]

    def list_stale_enrollments(
        self, tenant_id: TenantId, *, enrolled_before: datetime
    ) -> list[FaceProfile]:
        """Bənd 13 — «köhnəlmiş» qeydiyyatlar, ən köhnəsi əvvəldə.

        KƏSİM TARİXİ PARAMETRDİR, SQL-də hesablanmır: hədd
        (`FACE_REENROLLMENT_REMINDER_MONTHS`) ROOT-dan gəlir və sorğuya
        yazılsaydı, Root dəyəri dəyişəndə siyahı köhnə həddi göstərməyə davam
        edərdi.
        """
        rows = self._fetch_all(
            f"""{self._PROFILE_SELECT}
            WHERE tenant_id = %s
              AND is_active
              AND face_embedding IS NOT NULL
              AND face_enrolled_at < %s
            ORDER BY face_enrolled_at
            """,
            (tenant_id, enrolled_before),
        )
        return [self._row_to_profile(row) for row in rows]

    def list_all_profiles(self, tenant_id: TenantId) -> list[FaceProfile]:
        """BÜTÜN kirayəçinin qeydiyyatlı profilləri — dublikat aşkarlaması (6.2).

        Mağaza-scope-lu `list_store_profiles`-dan FƏRQLİ QƏSDƏN GENİŞ sorğudur:
        «başqa filialda ikinci qeydiyyat» sualı mağaza süzgəci ilə cavablanmazdı
        (bax port başlığı). Gecəlik toplu yoxlama üçündür — indeks
        (`idx_employees_face_enrolled`) kifayətdir.
        """
        rows = self._fetch_all(
            f"""{self._PROFILE_SELECT}
            WHERE tenant_id = %s
              AND is_active
              AND face_embedding IS NOT NULL
            ORDER BY id
            """,
            (tenant_id,),
        )
        return [self._row_to_profile(row) for row in rows]

    # -------------------------------- yazı ----------------------------------- #

    def save_enrollment(
        self, employee_id: EmployeeId, *, embedding: FaceEmbedding, enrolled_at: datetime
    ) -> None:
        """İstinad vektorunu ŞİFRƏLƏYİB yazır və qeydiyyat anını möhürləyir."""
        self._execute(
            """
            UPDATE employees
               SET face_embedding = %s,
                   face_enrolled_at = %s
             WHERE id = %s AND tenant_id = %s
            """,
            (
                self._encode_embedding(employee_id, embedding),
                enrolled_at,
                employee_id,
                self._tenant,
            ),
        )

    def save_security(
        self,
        employee_id: EmployeeId,
        *,
        mismatch_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        """ÜZ sayğacı və ÜZ kilidi — PIN sütunlarına TOXUNMUR.

        `pin_failed_attempts`/`pin_locked_until` bu `UPDATE`-də yoxdur və heç
        vaxt olmamalıdır: iki sayğacın ayrılığı bənd 3-ün əsas davranış
        qərarıdır və sxem onu iki ayrı sütunla ifadə edib.
        """
        self._execute(
            """
            UPDATE employees
               SET face_mismatch_attempts = %s,
                   face_locked_until = %s
             WHERE id = %s AND tenant_id = %s
            """,
            (mismatch_attempts, locked_until, employee_id, self._tenant),
        )

    def archive(
        self,
        employee_id: EmployeeId,
        *,
        archived_by: EmployeeId | None,
        reason: str | None,
        archived_at: datetime,
    ) -> bool:
        """Cari vektoru `REPLACED` statusu ilə arxivə köçürür (bənd 2).

        `INSERT ... SELECT` işlədilir (əvvəlcə oxuyub sonra yazmaq ƏVƏZİNƏ):
        vektor tətbiq qatına ÇIXMIR — yəni yenidən-qeydiyyat axını köhnə
        biometrik dəyəri Python yaddaşına gətirmir. Şifrələnmiş token olduğu
        kimi köçürülür, deməli AAD (`employee_id`) da dəyişmir.
        """
        affected = self._execute(
            """
            INSERT INTO face_embedding_history
                (tenant_id, employee_id, face_embedding, enrolled_at,
                 archived_at, status, archived_by, reason)
            SELECT tenant_id, id, face_embedding, face_enrolled_at,
                   %s, 'REPLACED', %s, %s
              FROM employees
             WHERE id = %s AND tenant_id = %s AND face_embedding IS NOT NULL
            """,
            (archived_at, archived_by, reason, employee_id, self._tenant),
        )
        return affected > 0

    def purge(
        self,
        employee_id: EmployeeId,
        *,
        purged_by: EmployeeId | None,
        reason: str | None,
        purged_at: datetime,
    ) -> bool:
        """Vektoru HƏR YERDƏN silir və arxivdə iz qoyur (bənd 8).

        ÜÇ ADDIM, BİR METOD — sıra vacibdir:

          1. cari qeydiyyat üçün `PURGED` izi yazılır (vektorsuz);
          2. ARXİVDƏ QALAN köhnə vektorlar da təmizlənir — bu addım olmadan
             bənd 8 SÜKUTLA pozulardı: `employees` sətri boşalar, biometrik
             məlumat isə `face_embedding_history`-də yaşamağa davam edərdi;
          3. `employees` sütunları `NULL`-lanır (sxemdəki cüt-invariant
             `chk_employee_face_enrollment_pair` üçün İKİSİ birlikdə).

        İDEMPOTENTDİR: ikinci çağırış heç nə tapmır və `False` qaytarır —
        deaktivasiya use case-i təkrar işə düşsə xəta vermir.
        """
        traced = self._execute(
            """
            INSERT INTO face_embedding_history
                (tenant_id, employee_id, face_embedding, enrolled_at,
                 archived_at, status, archived_by, reason)
            SELECT tenant_id, id, NULL, face_enrolled_at,
                   %s, 'PURGED', %s, %s
              FROM employees
             WHERE id = %s AND tenant_id = %s AND face_embedding IS NOT NULL
            """,
            (purged_at, purged_by, reason, employee_id, self._tenant),
        )
        archived_cleared = self._execute(
            """
            UPDATE face_embedding_history
               SET face_embedding = NULL,
                   status = 'PURGED'
             WHERE employee_id = %s AND tenant_id = %s AND face_embedding IS NOT NULL
            """,
            (employee_id, self._tenant),
        )
        self._execute(
            """
            UPDATE employees
               SET face_embedding = NULL,
                   face_enrolled_at = NULL
             WHERE id = %s AND tenant_id = %s
            """,
            (employee_id, self._tenant),
        )
        removed = traced > 0 or archived_cleared > 0
        if removed:
            _security_log.info(
                "FACE_EMBEDDING_PURGED",
                extra={
                    "employee_id": str(employee_id),
                    "archive_rows_cleared": archived_cleared,
                },
            )
        return removed

    # ------------------------------- köməkçi --------------------------------- #

    def _encode_embedding(self, employee_id: EmployeeId, embedding: FaceEmbedding) -> str:
        return self._encryption.encrypt(
            json.dumps(list(embedding.values)),
            context=_embedding_context(employee_id),
        )

    def _decode_embedding(self, employee_id: EmployeeId, token: str | None) -> FaceEmbedding | None:
        """Token-i vektora çevirir; AÇILMIRSA `None` (FAIL-CLOSED).

        Açılmama üç halda mümkündür: açar itib/dəyişib, token pozulub, və ya
        sətir BAŞQA işçidən köçürülüb (AAD uyğunsuzluğu). Üçü də eyni cavabı
        tələb edir — "bu işçinin doğrulana bilən qeydiyyatı YOXDUR" — və
        use case həmin halı manual təsdiqə yönləndirir (bənd 5 axını).

        İSTİSNA ATILMIR VƏ BU QƏSDƏNDİR: istisna kioskda xəta ekranı yaradar,
        işçi isə heç bir yol tapmazdı. `None` isə mövcud, sınanmış eskalasiya
        axınına düşür. Hadisə `security.log`-a CRITICAL kimi yazılır — səssiz
        deqradasiya deyil.
        """
        if token is None:
            return None
        try:
            raw = self._encryption.decrypt(token, context=_embedding_context(employee_id))
            values = json.loads(raw)
        except Exception as exc:
            _security_log.critical(
                "FACE_EMBEDDING_UNREADABLE",
                extra={
                    "employee_id": str(employee_id),
                    "error": type(exc).__name__,
                    "impact": "işçi üz təsdiqindən keçə bilməyəcək — manual təsdiqə düşür",
                },
            )
            return None
        if not isinstance(values, list) or not values:
            _security_log.critical(
                "FACE_EMBEDDING_MALFORMED", extra={"employee_id": str(employee_id)}
            )
            return None
        return FaceEmbedding(values=tuple(float(item) for item in values))

    def _row_to_profile(self, row: dict[str, Any]) -> FaceProfile:
        employee_id = EmployeeId(row["id"])
        return FaceProfile(
            employee_id=employee_id,
            tenant_id=TenantId(row["tenant_id"]),
            store_id=StoreId(row["store_id"]) if row["store_id"] is not None else None,
            embedding=self._decode_embedding(employee_id, row["face_embedding"]),
            # VEKTOR AÇILMAYIBSA TARİX DƏ VERİLMİR: `FaceProfile.is_enrolled`
            # hər ikisini tələb edir və yarımçıq profil «qeydiyyatlı, lakin
            # doğrulana bilməyən» işçi yaradardı.
            enrolled_at=row["face_enrolled_at"] if row["face_embedding"] is not None else None,
            mismatch_attempts=int(row["face_mismatch_attempts"] or 0),
            locked_until=row["face_locked_until"],
        )


class PostgresFaceVerificationLogRepository(_BaseRepository):
    """`face_verification_log` — hər cəhdin jurnalı (bənd 9, 12, 17, 18).

    `UPDATE` METODU YOXDUR: miqrasiya tətbiq rolundan `UPDATE` hüququnu geri
    alır (jurnal sətri FAKTdır). Metodu yazıb DB-nin rədd etməsinə buraxmaq
    "niyə işləmir?" sualı yaradardı — ona görə metod ÜMUMİYYƏTLƏ yoxdur
    (`exception_repositories.py` ilə eyni qərar).
    """

    _SELECT = """
        SELECT employee_id, tenant_id, store_id, occurred_at, result, trigger_context,
               matched_other_employee_id, lockout_triggered, confidence_score,
               is_low_confidence, liveness_action, duration_ms
        FROM face_verification_log
    """

    def record(self, entry: FaceVerificationLogEntry) -> None:
        self._execute(
            """
            INSERT INTO face_verification_log
                (tenant_id, employee_id, store_id, occurred_at, result, trigger_context,
                 matched_other_employee_id, lockout_triggered, confidence_score,
                 is_low_confidence, liveness_action, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry.tenant_id,
                entry.employee_id,
                entry.store_id,
                entry.occurred_at,
                entry.result.value,
                entry.trigger_context.value,
                entry.matched_other_employee_id,
                entry.lockout_triggered,
                entry.confidence_score,
                entry.is_low_confidence,
                entry.liveness_action.value if entry.liveness_action is not None else None,
                entry.duration_ms,
            ),
        )

    def purge_older_than(self, tenant_id: TenantId, *, cutoff: datetime) -> int:
        """Bənd 17 — saxlama müddəti təmizləməsi (`idx_face_verification_log_retention`)."""
        removed = self._execute(
            "DELETE FROM face_verification_log WHERE tenant_id = %s AND occurred_at < %s",
            (tenant_id, cutoff),
        )
        if removed:
            _log.info(
                "FACE_LOG_RETENTION_PURGE",
                extra={"tenant_id": str(tenant_id), "removed": removed},
            )
        return removed

    def list_mismatches_since(
        self, tenant_id: TenantId, *, since: datetime
    ) -> list[FaceVerificationLogEntry]:
        """`idx_face_verification_log_mismatch` qismən indeksinin sorğusu."""
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND result = 'MISMATCH' AND occurred_at >= %s
            ORDER BY occurred_at
            """,
            (tenant_id, since),
        )
        return [_row_to_log_entry(row) for row in rows]


class PostgresFaceExemptionRepository(_BaseRepository):
    """`face_control_exemptions` — PIN-only istisnası (bənd 14).

    `delete()` YOXDUR: miqrasiya `DELETE`-i geri alır — bağlanmış istisna
    «həmin gün bu işçi niyə üz təsdiqindən keçmirdi?» sualının cavabıdır.
    """

    _SELECT = """
        SELECT id, tenant_id, employee_id, granted_by, reason, granted_at, expires_at,
               status, revoked_by, revoked_at, revoke_reason
        FROM face_control_exemptions
    """

    def get(self, exemption_id: FaceExemptionId) -> FaceExemption | None:
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (exemption_id, self._tenant),
        )
        return _row_to_exemption(row) if row else None

    def active_for(self, employee_id: EmployeeId, *, now: datetime) -> FaceExemption | None:
        """QÜVVƏDƏ olan istisna — status VƏ vaxt şərti BİRLİKDƏ.

        Yalnız `status = 'ACTIVE'` yoxlasaydıq, gecəlik iş işləməyən terminalda
        (kompüter söndürülüb) müddəti bitmiş istisna sükutla uzanardı — yəni
        üz təsdiqindən azadlıq cron-un işləməsindən asılı olardı.
        """
        row = self._fetch_one(
            f"""{self._SELECT}
            WHERE employee_id = %s AND tenant_id = %s
              AND status = 'ACTIVE' AND expires_at > %s
            """,
            (employee_id, self._tenant, now),
        )
        return _row_to_exemption(row) if row else None

    def list_due_for_expiry(self, tenant_id: TenantId, *, now: datetime) -> list[FaceExemption]:
        """`idx_face_exemption_expiry` qismən indeksinin sorğusu (gecəlik iş)."""
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND status = 'ACTIVE' AND expires_at <= %s
            ORDER BY expires_at
            """,
            (tenant_id, now),
        )
        return [_row_to_exemption(row) for row in rows]

    def list_active(self, tenant_id: TenantId, *, now: datetime) -> list[FaceExemption]:
        rows = self._fetch_all(
            f"""{self._SELECT}
            WHERE tenant_id = %s AND status = 'ACTIVE' AND expires_at > %s
            ORDER BY expires_at
            """,
            (tenant_id, now),
        )
        return [_row_to_exemption(row) for row in rows]

    def save(self, exemption: FaceExemption) -> None:
        """UPSERT — `ON CONFLICT (id)`.

        YALNIZ QƏRAR SÜTUNLARI YENİLƏNİR: `employee_id`, `granted_by`,
        `reason` və `granted_at` təyinat anının FAKTIdır. `expires_at` isə
        yenilənir, çünki uzatma məhz onu dəyişir (yeni sətir yaratmaq
        `ux_face_exemption_active` indeksinə görə onsuz da mümkün deyil).
        """
        self._execute(
            """
            INSERT INTO face_control_exemptions
                (id, tenant_id, employee_id, granted_by, reason, granted_at, expires_at,
                 status, revoked_by, revoked_at, revoke_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET expires_at    = EXCLUDED.expires_at,
                    status        = EXCLUDED.status,
                    revoked_by    = EXCLUDED.revoked_by,
                    revoked_at    = EXCLUDED.revoked_at,
                    revoke_reason = EXCLUDED.revoke_reason
            """,
            (
                exemption.exemption_id,
                exemption.tenant_id,
                exemption.employee_id,
                exemption.granted_by,
                exemption.reason,
                exemption.granted_at,
                exemption.expires_at,
                exemption.status.value,
                exemption.revoked_by,
                exemption.revoked_at,
                exemption.revoke_reason,
            ),
        )


class PostgresFaceStoreScopeRepository(_BaseRepository):
    """`face_control_store_scope` — mağaza-səviyyəli aktivlik (bənd 15)."""

    def active_scope(self, tenant_id: TenantId) -> FaceStoreScope:
        """AKTİV sətirlər. Heç biri yoxdursa BOŞ dəst = qlobal davranış."""
        rows = self._fetch_all(
            """
            SELECT store_id FROM face_control_store_scope
             WHERE tenant_id = %s AND is_active
            """,
            (tenant_id,),
        )
        return FaceStoreScope(store_ids=frozenset(StoreId(row["store_id"]) for row in rows))

    def set_active(
        self, tenant_id: TenantId, store_id: StoreId, *, active: bool, changed_by: EmployeeId
    ) -> None:
        """UPSERT — `ON CONFLICT (tenant_id, store_id)`, SOFT DELETE ilə.

        Çıxarmada sətir SİLİNMİR: `chk_face_scope_deactivation` çıxarılmış
        sətrin `deactivated_at`-ını MƏCBUR edir, yəni "bu mağazada Face
        Control nə vaxt söndürüldü?" sualı həmişə cavablanır.
        """
        self._execute(
            """
            INSERT INTO face_control_store_scope
                (tenant_id, store_id, added_by, is_active, deactivated_at, deactivated_by)
            VALUES (%s, %s, %s, %s, CASE WHEN %s THEN NULL ELSE now() END,
                    CASE WHEN %s THEN NULL ELSE %s END)
            ON CONFLICT (tenant_id, store_id) DO UPDATE
                SET is_active      = EXCLUDED.is_active,
                    deactivated_at = EXCLUDED.deactivated_at,
                    deactivated_by = EXCLUDED.deactivated_by
            """,
            (tenant_id, store_id, changed_by, active, active, active, changed_by),
        )


def _embedding_context(employee_id: EmployeeId) -> str:
    """AAD sətri — token-i ÖZ sətrinə bağlayır (bax modul başlığı)."""
    return f"face_embedding:{employee_id}"


def _row_to_log_entry(row: dict[str, Any]) -> FaceVerificationLogEntry:
    gesture = row["liveness_action"]
    return FaceVerificationLogEntry(
        employee_id=EmployeeId(row["employee_id"]),
        tenant_id=TenantId(row["tenant_id"]),
        result=FaceVerificationResult(row["result"]),
        trigger_context=FaceTriggerContext(row["trigger_context"]),
        occurred_at=row["occurred_at"],
        store_id=StoreId(row["store_id"]) if row["store_id"] is not None else None,
        matched_other_employee_id=(
            EmployeeId(row["matched_other_employee_id"])
            if row["matched_other_employee_id"] is not None
            else None
        ),
        lockout_triggered=bool(row["lockout_triggered"]),
        confidence_score=(
            float(row["confidence_score"]) if row["confidence_score"] is not None else None
        ),
        is_low_confidence=bool(row["is_low_confidence"]),
        # Sütunda SƏRT `CHECK` YOXDUR (aktiv siyahı ROOT parametridir), ona görə
        # naməlum dəyər `None`-a düşür: köhnə sətir yeni buraxılışda hesabatı
        # çökdürməməlidir (`ExceptionSeverity.parse` ilə eyni fəlsəfə).
        liveness_action=_parse_gesture(gesture),
        duration_ms=int(row["duration_ms"]) if row["duration_ms"] is not None else None,
    )


def _parse_gesture(raw: str | None) -> LivenessGesture | None:
    if raw is None:
        return None
    try:
        return LivenessGesture(raw.strip().upper())
    except ValueError:
        return None


def _row_to_exemption(row: dict[str, Any]) -> FaceExemption:
    return FaceExemption(
        exemption_id=FaceExemptionId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        employee_id=EmployeeId(row["employee_id"]),
        granted_by=EmployeeId(row["granted_by"]),
        reason=str(row["reason"]),
        granted_at=row["granted_at"],
        expires_at=row["expires_at"],
        status=FaceExemptionStatus(row["status"]),
        revoked_by=EmployeeId(row["revoked_by"]) if row["revoked_by"] is not None else None,
        revoked_at=row["revoked_at"],
        revoke_reason=row["revoke_reason"],
    )


__all__ = [
    "PostgresFaceEmbeddingRepository",
    "PostgresFaceExemptionRepository",
    "PostgresFaceStoreScopeRepository",
    "PostgresFaceVerificationLogRepository",
]
