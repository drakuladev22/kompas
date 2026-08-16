"""Offline sinxronizasiya konfliktlərinin manual həlli (bölmə 5) — Faza 5.

    "Konflikt aşkarlandıqda hər iki versiya saxlanılır, `CONFLICT` statusu ilə
     HR_Admin-ə MANUAL HƏLL üçün göndərilir." (bölmə 5)

`infrastructure/offline/sync.py` konflikti AŞKARLAYIR və `sync_conflicts`-ə
yazır. Bu modul həmin sətirlərin insan tərəfindən həll edilməsini idarə edir —
onsuz cədvəl sonsuza qədər böyüyər və "manual həll" heç vaxt baş verməzdi.

──────────────────────────────────────────────────────────────────────────────
KONFLİKT ANINDA HƏDƏF SƏTİRDƏ HANSI VERSİYA DURUR (bütün qərarların əsası)
──────────────────────────────────────────────────────────────────────────────
`OfflineSyncService._apply()` divergensiya görəndə audit-kritik cədvəl üçün
`_record_conflict(...)` çağırıb DƏRHAL `return "CONFLICT"` edir — `_upsert()`
XƏTTİ İCRA OLUNMUR. Yəni yerli (offline) yazı hədəf cədvələ HEÇ VAXT
düşmür və sətirdə **UZAQ (bulud) versiya** durur; bunu
`tests/e2e/test_qt_scaffolding.py`-dəki "Audit-kritik cədvəl konfliktdə
ÜZƏRİNƏ yazılmamalıdır" iddiası da qoruyur.

Bu FAKT üç həll variantının mənasını təyin edir:

    KEPT_LOCAL   — hədəfdə uzaq versiya durur → YERLİ versiya FAKTİKİ olaraq
                   yazılmalıdır. Yazılmasa qərar sənəddə qalar, məlumat isə
                   dəyişməzdi (məhz düzəldilən qüsur budur).
    KEPT_REMOTE  — hədəfdə onsuz da uzaq versiya durur → BOŞ ƏMƏLİYYAT.
                   Bu, "unudulmuş kod" deyil, DOĞRU nəticədir və audit izində
                   `target_rows_written = 0` kimi AÇIQ görünür.
    MERGED       — sistem sahə-sahə birləşdirmə APARMIR (bax aşağı).

Hər üç halda `sync_conflicts.local_version`/`remote_version` sütunları
TOXUNULMAZ qalır. Bölmə 5 audit-kritik cədvəllər üçün last-write-wins-i
qadağan edir; həll qərarı da həmin audit izinin bir hissəsidir.

──────────────────────────────────────────────────────────────────────────────
ATOMİKLİK — SAGA DEYİL, TƏK TRANZAKSİYA
──────────────────────────────────────────────────────────────────────────────
Konfliktin bağlanması və hədəf sətrin yazılması EYNİ repository-nin, deməli
eyni `PostgresUnitOfWork` bağlantısının üzərindən gedir — ikisi bir SQL
tranzaksiyasındadır və `session.commit()` ikisini birlikdə təsdiqləyir.
`LeaveVerificationUseCase.verify_return` naxışı (Saga + kompensasiya) BURADA
RƏDD EDİLDİ: Saga MÜXTƏLİF resurslara (status + cərimə + audit, hər biri ayrı
aqreqat) toxunan və qismən uğursuzluğu geri qaytarıla bilməyən əməliyyat
üçündür. Burada isə hər iki yazı TEK bazadadır və `ROLLBACK` tam kompensasiya
verir — Saga əlavə vəziyyət maşını gətirib heç nə qazandırmazdı
(`morning_check_in.py` başlığı ilə eyni mühakimə).

SIRA QƏSDƏNDİR: ƏVVƏL konflikt bağlanır (`resolve()` `resolved_at IS NULL`
şərti ilə "sahiblənir"), SONRA hədəf sətir yazılır. Əks sıra yarış halında
məlumatı korlayardı: iki HR eyni anda qərar versə, ikincinin hədəf yazısı
tətbiq olunar, konflikt sətri isə birincinin qərarını saxlayardı — yəni audit
"KEPT_REMOTE" deyərkən cədvəldə yerli versiya dayanardı. İndi sahiblənə
bilməyən ikinci çağırış hədəfə TOXUNMADAN `ConflictNotFoundError` alır.

──────────────────────────────────────────────────────────────────────────────
`MERGED` — VARİANT (a): "ƏL İLƏ DÜZƏLDİLƏCƏK" KİMİ RƏSMİLƏŞDİRİLİB
──────────────────────────────────────────────────────────────────────────────
Nə use case, nə repository, nə də ekran sahə-sahə seçim qəbul edir
(`controllers/sync_conflicts.py` bunu istifadəçiyə AÇIQ yazır). İki yol var
idi: (a) `MERGED`-i "heç nə yazılmır, düzəliş əl ilə aparılacaq" kimi
rəsmiləşdirmək, (b) sahə seçicisini həqiqətən qurmaq.

(a) SEÇİLDİ. Spesifikasiya bölmə 5 sahə-birləşdirmə TƏLƏB ETMİR — yalnız
"manual həll" deyir; (b) isə `resolve()` imzasını, repository-ni və ekranı
dəyişib YENİ səhv mənbəyi yaradardı: yarımçıq seçilmiş sahə dəsti həm yerli,
həm uzaq versiyadan fərqli, HEÇ VAXT MÖVCUD OLMAMIŞ üçüncü sətir qurardı və
onun düzgünlüyünü heç nə yoxlaya bilməzdi.

DÜRÜSTLÜK ONDADIR Kİ, `MERGED` ARTIQ SÜKUTLA "HƏLL OLUNDU" DEMİR: audit izi
`applied_version = "REMOTE"` (yəni cədvəldə hələ də bulud versiyası durur) və
`manual_correction_required = True` yazır, əməliyyat kanalına isə xəbərdarlıq
düşür. Beləliklə açıq qalan iş GÖRÜNÜR — əvvəl görünmürdü.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA `can_resolve_sync_conflicts` FLAG-İ (SEC-018)
──────────────────────────────────────────────────────────────────────────────
Qapı əvvəl `can_view_employee_reports` idi. O flag BAXIŞ hüququdur və
`schema.sql` §23-də `Mağaza_Meneceri`-yə DEFOLT VERİLİR. Əməliyyat heç nə
yazmadığı müddətdə bu zərərsiz idi; yuxarıdakı düzəlişdən sonra isə hər
mağaza meneceri ÖZ filialının cərimə/icazə sətrini "konflikt həlli" adı
altında yerli versiya ilə əvəz edə bilərdi — yəni bütün anti-fraud qatını
(kamera təsdiqi, dual-control, aylıq icmal) bir düymə ilə yan keçərdi.

Ona görə yeni flag ANTI-FRAUD işarəlidir (`is_anti_fraud = TRUE`): qayda İKİ
yerdədir — domendə `PermissionFlag.assert_grantable_to()`
(`ANTI_FRAUD_FORBIDDEN_ROLES`), bazada isə `enforce_anti_fraud_segregation()`
(`schema.sql` §18) — və hər ikisi HƏM rol-defoltunu, HƏM fərdi override-ı
bloklayır. Trigger-in ÖZÜ dəyişmir: o, `permission_flags` sətrini oxuyaraq
işləyir, yeni sətir kifayətdir (miqrasiya 056, `038` ilə eyni naxış).

Hardlock səviyyəsi `NONE` (0) SEÇİLDİ, daha yüksəyi YOX: bölmə 5 həlli AÇIQ
şəkildə `HR_Admin`-ə verir, `HR_Admin` isə `OPERATIONAL` (3) pilləsindədir və
istənilən 1/2/3 səviyyəsi (`ROOT_ONLY`/`ROOT_CEO`/`DELEGABLE`) onu STRUKTUR
olaraq kənarlaşdırıb spesifikasiyanı pozardı.

OXU DA EYNİ FLAG ARXASINDADIR: bu ekranın yeganə məqsədi həlldir və yalnız
baxan istifadəçi hər düymədə "səlahiyyətiniz yoxdur" alardı. Müstəqil nəzarət
itmir — qərarların tarixçəsi `can_view_audit_logs` ilə oxunur
(`exception_engine.py::_require_view` ilə eyni mühakimə: "OXU VƏ QƏRAR EYNİ
FLAG-DƏDİR").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.application.root_limits import fallback_int, limit_int
from src.domain.policies import SystemLimitKey
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import AuditTrail, Clock, SystemLimits
    from src.domain.value_objects.identifiers import EmployeeId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

#: Konflikt həlli qapısı — YAZI hüququdur (bax modul başlığı, SEC-018).
#:
#: Kataloq sətri `migrations/056`-dadır: `is_anti_fraud = TRUE`,
#: `excludes_camera_role = TRUE`, `hardlock_level = 0`.
RESOLVE_CONFLICT_FLAG = "can_resolve_sync_conflicts"

MIN_NOTE_LENGTH = 5

#: `UPDATE`-i DB trigger-i ilə bloklanan cədvəllər (SEC-007, `schema.sql` §26).
#:
#: `audit_logs` append-only-dir, ona görə `KEPT_LOCAL` orada TƏTBİQ EDİLƏ
#: BİLMƏZ. Praktikada belə konflikt yaranmır — `sync.VERSION_COLUMN` bu cədvəl
#: üçün `None`-dur və `_is_diverged()` həmişə `False` qaytarır. Yoxlama YENƏ DƏ
#: var, çünki köhnə/əl ilə salınmış sətir mövcud ola bilər və o halda tətbiq
#: trigger-in xam PostgreSQL xətası ilə çökərdi; indi HR Azərbaycan dilində
#: aydın izah alır və konflikt AÇIQ qalır (sükutla uduzmaq QADAĞANDIR).
APPEND_ONLY_TABLES = frozenset({"audit_logs"})

#: İnbox-un bir oxunuşda gətirdiyi konflikt sayı.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits`
#: (`SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE`, seed: migrations/034). Uzun
#: offline dövrdən sonra konflikt sayı sıçrayır və HR bir dəfəyə neçəsini
#: görmək istədiyi quraşdırmadan-quraşdırmaya fərqlənir.
DEFAULT_INBOX_PAGE_SIZE = fallback_int(SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE)


class ConflictResolutionError(KompasOSError):
    """Konflikt həlli icra edilə bilmədi."""

    user_message = "Konflikt həll edilə bilmədi."


class ConflictNotFoundError(ConflictResolutionError):
    user_message = "Konflikt qeydi tapılmadı."


class ConflictTargetWriteError(ConflictResolutionError):
    """Seçilmiş versiya HƏDƏF sətrə yazıla bilmədi.

    Ayrıca sinifdir, çünki nəticəsi digərlərindən KEYFİYYƏTCƏ fərqlidir:
    tranzaksiya geri qayıdır və konflikt AÇIQ qalır. İstifadəçi mesajı bunu
    açıq deyir ki, HR "həll etdim" zənn edib siyahını tərk etməsin.
    """

    user_message = "Seçilmiş versiya qeydə yazıla bilmədi — konflikt açıq qaldı."


class Resolution(str, Enum):
    """`sync_conflicts.resolution` — DB `CHECK` ilə EYNİ dəyərlər."""

    KEPT_LOCAL = "KEPT_LOCAL"
    KEPT_REMOTE = "KEPT_REMOTE"
    MERGED = "MERGED"

    @property
    def label_az(self) -> str:
        return _RESOLUTION_LABELS[self]

    @property
    def requires_target_write(self) -> bool:
        """Hədəf sətrə FAKTİKİ yazı lazımdırmı.

        YALNIZ `KEPT_LOCAL` — çünki konflikt anında hədəfdə UZAQ versiya durur
        (bax modul başlığı). Qayda burada, `Resolution`-un özündə yaşayır ki,
        use case ilə repository eyni cavabı iki yerdə hesablamasın.
        """
        return self is Resolution.KEPT_LOCAL

    @property
    def standing_version(self) -> str:
        """Həlldən SONRA hədəf sətirdə DURAN versiya — audit izinin əsası.

        `MERGED` üçün `REMOTE`-dur, `MERGED` DEYİL: variant (a)-da heç nə
        yazılmır, yəni cədvəldə hələ də bulud versiyası dayanır. "MERGED"
        yazsaydıq audit birləşdirilmiş sətrin mövcud olduğunu iddia edərdi —
        məhz düzəldilən yalanın təkrarı olardı.
        """
        return "LOCAL" if self is Resolution.KEPT_LOCAL else "REMOTE"


_RESOLUTION_LABELS: dict[Resolution, str] = {
    Resolution.KEPT_LOCAL: "Mağazadakı versiya saxlanıldı",
    Resolution.KEPT_REMOTE: "Buluddakı versiya saxlanıldı",
    Resolution.MERGED: "Hər iki versiyadan birləşdirildi",
}


@dataclass(frozen=True)
class ConflictItem:
    """Həll gözləyən bir konflikt — ekranın yan-yana göstərdiyi iki versiya."""

    conflict_id: object
    table_name: str
    record_id: object
    local_version: dict[str, Any]
    remote_version: dict[str, Any]
    detected_at: datetime

    def differing_fields(self) -> list[str]:
        """Yalnız FƏRQLİ sahələr — ekran onları vurğulayır.

        Bütün sahələri göstərmək 30 sütunlu bir cərimə sətrində fərqi
        gözdən itirərdi; HR məhz fərqə baxıb qərar verir.
        """
        keys = set(self.local_version) | set(self.remote_version)
        return sorted(
            key for key in keys if self.local_version.get(key) != self.remote_version.get(key)
        )

    @property
    def is_audit_critical(self) -> bool:
        """Bölmə 5-də adı çəkilən cədvəllər — ekranda xəbərdarlıq nişanı."""
        return self.table_name in AUDIT_CRITICAL_TABLES


#: Bölmə 5: "audit-kritik cədvəllər (leave_requests, fines, audit_logs)".
AUDIT_CRITICAL_TABLES = frozenset({"leave_requests", "fines", "audit_logs"})


@runtime_checkable
class SyncConflictRepository(Protocol):
    """`sync_conflicts` cədvəli."""

    def list_open(
        self, tenant_id: TenantId, *, limit: int = DEFAULT_INBOX_PAGE_SIZE
    ) -> list[ConflictItem]: ...

    def get(self, conflict_id: object) -> ConflictItem | None: ...

    def open_count(self, tenant_id: TenantId) -> int: ...

    def resolve(
        self,
        conflict_id: object,
        *,
        resolution: Resolution,
        resolved_by: EmployeeId,
        resolved_at: datetime,
        note: str,
    ) -> bool:
        """Konflikti bağlayır və SAHİBLƏNİB-SAHİBLƏNMƏDİYİNİ qaytarır.

        `True` = bu çağırış konflikti bağladı; `False` = artıq bağlı idi
        (başqa HR qabaqladı). Qaytarılan dəyər OLMADAN yarış halı sükutla
        udulurdu: ikinci çağırış heç nə dəyişmirdi, lakin auditə öz qərarını
        yazırdı — bax modul başlığındakı "SIRA QƏSDƏNDİR" bölməsi.
        """
        ...

    def apply_local_version(
        self,
        *,
        table_name: str,
        record_id: object,
        local_version: Mapping[str, Any],
    ) -> int:
        """Yerli (offline) versiyanı HƏDƏF sətrə yazır, yazılan sətir sayını qaytarır.

        `0` = hədəf sətir tapılmadı və ya yazılası sütun qalmadı; çağıran bunu
        XƏTA sayır və tranzaksiyanı geri qaytarır (yarımçıq hal — konflikt
        bağlı, məlumat köhnə — indiki vəziyyətdən pisdir, çünki artıq
        görünmür).
        """
        ...


class SyncConflictUseCase:
    """HR-ın konflikt həlli inbox-u."""

    def __init__(
        self,
        *,
        repository: SyncConflictRepository,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        # `limits` İSTƏYƏ BAĞLIDIR: `None` halında səhifə ölçüsü
        # `DEFAULT_INBOX_PAGE_SIZE` fallback-ıdır — davranış köçürmədən
        # ƏVVƏLKİ ilə HƏRFƏN eynidir.
        self._repository = repository
        self._audit = audit
        self._clock = clock
        self._limits = limits

    def inbox(self, *, tenant_id: TenantId, actor: Employee) -> list[ConflictItem]:
        """Həll gözləyən konfliktlər — audit-kritik olanlar əvvəldə."""
        self._require(actor)
        items = self._repository.list_open(
            tenant_id,
            limit=limit_int(self._limits, tenant_id, SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE),
        )
        return sorted(items, key=lambda item: (not item.is_audit_critical, item.detected_at))

    def open_count(self, *, tenant_id: TenantId, actor: Employee) -> int:
        """Menyu nişanı üçün sayğac."""
        self._require(actor)
        return self._repository.open_count(tenant_id)

    def resolve(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        conflict_id: object,
        resolution: Resolution,
        note: str,
    ) -> ConflictItem:
        """Konflikti bağlayır VƏ seçilmiş versiyanı hədəf sətrə TƏTBİQ EDİR.

        `sync_conflicts.local_version`/`remote_version` sütunları toxunulmaz
        qalır (bölmə 5) — dəyişən yalnız HƏDƏF cədvəldəki sətirdir və yalnız
        `KEPT_LOCAL` halında.

        Raises:
            ConflictResolutionError: səlahiyyət yoxdursa, qeyd qısadırsa və ya
                append-only cədvələ `KEPT_LOCAL` tətbiq edilmək istənirsə.
            ConflictNotFoundError: konflikt yoxdursa və ya artıq bağlanıbsa.
            ConflictTargetWriteError: hədəf sətir yazıla bilmədisə.
        """
        self._require(actor)
        cleaned = " ".join(note.split())
        if len(cleaned) < MIN_NOTE_LENGTH:
            raise ConflictResolutionError(
                f"Həll qeydi minimum {MIN_NOTE_LENGTH} simvol olmalıdır",
                user_message="Qərarınızın səbəbini yazın.",
                context={"length": len(cleaned)},
            )

        item = self._repository.get(conflict_id)
        if item is None:
            raise ConflictNotFoundError(
                "Konflikt qeydi tapılmadı", context={"conflict_id": str(conflict_id)}
            )

        # APPEND-ONLY YOXLAMASI HƏR ŞEYDƏN ƏVVƏLDİR: konflikti bağlayıb sonra
        # yazının mümkünsüz olduğunu görmək tranzaksiyanı boş yerə geri
        # qaytarardı və HR səbəbi yalnız ümumi xətadan oxuyardı.
        if resolution.requires_target_write and item.table_name in APPEND_ONLY_TABLES:
            raise ConflictResolutionError(
                f"'{item.table_name}' append-only cədvəldir — «{resolution.label_az}» "
                f"tətbiq edilə bilməz",
                user_message=(
                    "Audit jurnalı dəyişdirilə bilməz: bu konflikt üçün yalnız "
                    "«Buluddakı versiya saxlanıldı» və ya «Hər iki versiyadan "
                    "birləşdirildi» seçilə bilər."
                ),
                context={"table": item.table_name, "resolution": resolution.value},
            )

        now = self._clock.now()

        # 1. SAHİBLƏNMƏ — `resolved_at IS NULL` şərti ilə. Hədəf yazısından
        #    ƏVVƏL olması qəsdəndir (bax modul başlığı: yarış halında ikinci
        #    HR məlumata TOXUNMADAN geri qaytarılır).
        claimed = self._repository.resolve(
            conflict_id,
            resolution=resolution,
            resolved_by=actor.id,
            resolved_at=now,
            note=cleaned,
        )
        if not claimed:
            raise ConflictNotFoundError(
                "Konflikt artıq bağlanıb — qərarı başqa istifadəçi yazıb",
                context={"conflict_id": str(conflict_id)},
            )

        # 2. TƏTBİQ — yalnız `KEPT_LOCAL`. Eyni tranzaksiyadadır: burada
        #    atılan istisna 1-ci addımı da geri qaytarır.
        written = 0
        if resolution.requires_target_write:
            written = self._repository.apply_local_version(
                table_name=item.table_name,
                record_id=item.record_id,
                local_version=item.local_version,
            )
            if written == 0:
                raise ConflictTargetWriteError(
                    "Yerli versiya hədəf sətrə yazılmadı — sətir tapılmadı və ya "
                    "yazılası sütun qalmadı",
                    context={"table": item.table_name, "record_id": str(item.record_id)},
                )

        if resolution is Resolution.MERGED:
            # Variant (a): birləşdirmə ƏL İLƏ aparılacaq. Xəbərdarlıq audit
            # kanalınadır ki, açıq qalan iş yalnız `sync_conflicts` sətrində
            # gizlənməsin — konflikt siyahıdan ÇIXIR, düzəliş isə hələ qalır.
            _audit_log.warning(
                "SYNC_CONFLICT_MANUAL_MERGE_PENDING",
                extra={
                    "table": item.table_name,
                    "record_id": str(item.record_id),
                    "actor_id": str(actor.id),
                    "action": "Birləşdirilmiş dəyər müvafiq ekranda əl ilə qurulmalıdır",
                },
            )

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="SYNC_CONFLICT_RESOLVED",
            entity_type=item.table_name,
            entity_id=item.record_id,
            before_state={
                "local": item.local_version,
                "remote": item.remote_version,
                # Konflikt anında hədəfdə DURAN versiya — bax modul başlığı.
                # Onsuz `after_state` hansı istiqamətə dəyişiklik olduğunu
                # göstərməzdi.
                "standing": "REMOTE",
            },
            after_state={
                "resolution": resolution.value,
                "applied_version": resolution.standing_version,
                "target_table": item.table_name,
                "target_rows_written": written,
                "manual_correction_required": resolution is Resolution.MERGED,
            },
            reason=cleaned,
        )
        return item

    def _require(self, actor: Employee) -> None:
        if not actor.has_permission(RESOLVE_CONFLICT_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "SYNC_CONFLICT_ACCESS_DENIED",
                extra={"actor_id": str(actor.id), "flag": RESOLVE_CONFLICT_FLAG},
            )
            raise ConflictResolutionError(
                f"«{RESOLVE_CONFLICT_FLAG}» səlahiyyəti yoxdur",
                user_message="Sinxronizasiya konfliktlərini həll etmək səlahiyyətiniz yoxdur.",
                context={"actor_id": str(actor.id)},
            )


__all__ = [
    "APPEND_ONLY_TABLES",
    "AUDIT_CRITICAL_TABLES",
    "DEFAULT_INBOX_PAGE_SIZE",
    "MIN_NOTE_LENGTH",
    "RESOLVE_CONFLICT_FLAG",
    "ConflictItem",
    "ConflictNotFoundError",
    "ConflictResolutionError",
    "ConflictTargetWriteError",
    "Resolution",
    "SyncConflictRepository",
    "SyncConflictUseCase",
]
