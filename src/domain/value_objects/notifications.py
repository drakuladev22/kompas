"""Bildiriş kateqoriyaları və kritiklik qaydası (bölmə 7) — Faza 3.12.

Spesifikasiya: *"Kritik bildirişlər (timeout eskalasiyası, dual-control təsdiq
gözləyir, ödəniş xatırlatması, LICENSE_INACTIVE xəbərdarlığı, tapşırıq
son-tarix eskalasiyası, `PENDING_RECONCILIATION` statusuna keçən Saga
əməliyyatı — sistemin ən ciddi məlumat-bütövlüyü vəziyyəti olduğu üçün heç
vaxt sükutla qeyd olunmamalıdır) ... eyni zamanda qeydiyyatlı admin e-poçtuna
da göndərilir."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ KRİTİKLİK ÇAĞIRANDAN TAM ASILI DEYİL
──────────────────────────────────────────────────────────────────────────────
`notify(..., is_critical=True)` imzası özlüyündə kifayətdir — LAKİN yalnız
çağıran tərəf onu unutmadıqda. Spesifikasiyada sadalanan altı kateqoriya isə
məhz "unudulmamalı" olanlardır: `PENDING_RECONCILIATION` sistemin ən ciddi
məlumat-bütövlüyü vəziyyətidir və bir `True` yazmağı unutmaq onu sükuta
çevirərdi.

Ona görə kateqoriya siyahısı BURADA, domendə saxlanılır və bildiriş qatı
`is_critical`-i məcburi olaraq YÜKSƏLDİR (heç vaxt endirmir): çağıran istədiyi
şeyi kritik edə bilər, lakin sadalananları qeyri-kritik EDƏ BİLMƏZ.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable


class NotificationCategory(str, Enum):
    """`notifications.category` dəyərləri."""

    TIMEOUT_ESCALATION = "TIMEOUT_ESCALATION"
    DUAL_CONTROL_PENDING = "DUAL_CONTROL_PENDING"
    PAYMENT_REMINDER = "PAYMENT_REMINDER"
    LICENSE_INACTIVE = "LICENSE_INACTIVE"
    TASK_DEADLINE = "TASK_DEADLINE"
    SAGA_PENDING_RECONCILIATION = "SAGA_PENDING_RECONCILIATION"
    # Aşağıdakılar məlumatlandırıcıdır — e-poçt fallback-ı tələb etmir.
    FINE_ISSUED = "FINE_ISSUED"
    LEAVE_DECISION = "LEAVE_DECISION"
    SHIFT_SWAP = "SHIFT_SWAP"
    POINTS_RESET_UPCOMING = "POINTS_RESET_UPCOMING"
    ERP_SYNC_FAILED = "ERP_SYNC_FAILED"

    @property
    def is_always_critical(self) -> bool:
        return self.value in ALWAYS_CRITICAL_CATEGORIES

    @property
    def label_az(self) -> str:
        return _LABELS_AZ.get(self, self.value)


#: Bölmə 7-də adbaad sadalanan altı kateqoriya — HƏMİŞƏ e-poçt fallback-ı alır.
#: Sətir (Enum yox) saxlanılır ki, gələcəkdə DB-dən gələn naməlum kateqoriya
#: adı da bu siyahıya salına bilsin.
ALWAYS_CRITICAL_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "TIMEOUT_ESCALATION",
        "DUAL_CONTROL_PENDING",
        "PAYMENT_REMINDER",
        "LICENSE_INACTIVE",
        "TASK_DEADLINE",
        "SAGA_PENDING_RECONCILIATION",
    }
)

_LABELS_AZ: Final[dict[NotificationCategory, str]] = {
    NotificationCategory.TIMEOUT_ESCALATION: "Təsdiq gecikməsi",
    NotificationCategory.DUAL_CONTROL_PENDING: "İkili nəzarət təsdiqi gözlənilir",
    NotificationCategory.PAYMENT_REMINDER: "Ödəniş xatırlatması",
    NotificationCategory.LICENSE_INACTIVE: "Lisenziya deaktivdir",
    NotificationCategory.TASK_DEADLINE: "Tapşırıq son tarixi",
    NotificationCategory.SAGA_PENDING_RECONCILIATION: "Uzlaşdırma tələb olunur",
    NotificationCategory.FINE_ISSUED: "Cərimə tətbiq edildi",
    NotificationCategory.LEAVE_DECISION: "İcazə qərarı",
    NotificationCategory.SHIFT_SWAP: "Növbə dəyişikliyi",
    NotificationCategory.POINTS_RESET_UPCOMING: "Xal sıfırlanması yaxınlaşır",
    NotificationCategory.ERP_SYNC_FAILED: "1C sinxronizasiya xətası",
}


def is_critical_category(category: str) -> bool:
    """Kateqoriya HƏMİŞƏ kritikdirmi (çağıranın bayrağından asılı olmayaraq)."""
    return category.strip().upper() in ALWAYS_CRITICAL_CATEGORIES


# --------------------------------------------------------------------------- #
# TENANT SƏVİYYƏLİ BİLDİRİŞİN AUDİTORİYASI
# --------------------------------------------------------------------------- #
#
# `notifications.recipient_id` NULL olduqda sətir konkret işçiyə ünvanlanmayıb —
# o, "bunu edə bilən adam görsün" deməkdir. Marşrutlaşdırma qaydası əvvəllər
# HEÇ YERDƏ yazılmamışdı və panel belə sətirləri HAMIYA göstərirdi: adi
# `Satıcı` "manual vaxt düzəlişi təsdiq gözləyir" və ya "Drive-da yer qalmayıb"
# sətirlərini görürdü. Bu, bölmə 3-ün "GÖRMƏK = SƏLAHİYYƏTİN OLMASI"
# prinsipinə ziddir və eyni zamanda həqiqi bildirişləri səs-küydə itirirdi.
#
# CƏDVƏL HARDAN GƏLİR — UYDURULMUR. Hər sətir ya `notify()` çağırışının
# yanındakı şərhdə adı çəkilən alıcıdan, ya da bildirişin TƏLƏB ETDİYİ
# əməliyyatı qoruyan flag-dən götürülüb. Rol adları (`HR_Admin`, `Mağaza
# Meneceri`, `CEO`) `schema.sql` §23-dəki rol → flag seed-i ilə flag-ə
# çevrilib; seçilən flag həmin rolların HAMISINDA var və adı çəkilməyən
# rollarda yoxdur.
#
# BOŞLUQ = FAIL-OPEN. Cədvəldə OLMAYAN kateqoriya HAMIYA görünür (mövcud
# davranış saxlanılır). Əks istiqamət — naməlum kateqoriyanı gizlətmək —
# rədd edildi: yeni modul öz kateqoriyasını əlavə etdikdə bildiriş sükutla
# heç kimə çatmazdı və səbəbi heç bir jurnalda görünməzdi.
#
# ŞƏXSİ SƏTİR (`recipient_id = <işçi>`) BU CƏDVƏLDƏN ASILI DEYİL — o, HƏMİŞƏ
# öz sahibinə görünür: "cərimə etirazınız rədd edildi" sətrini işçidən
# gizlətmək bildirişin bütün məqsədini pozardı.
TENANT_NOTIFICATION_AUDIENCE: Final[dict[str, tuple[str, ...]]] = {
    # `leave_verification.escalate_timeouts` / `morning_check_in.escalate_timeouts`:
    # mətn açıq deyir ki, "HR_Admin və ya CEO manual təsdiq edə bilər".
    # Həmin yolun qapısı `_require_camera_permission`-dadır: normal halda
    # `can_verify_returns`, timeout-dan sonra isə `can_approve_dual_control_override`.
    # Auditoriya məhz bu iki flag-dir — biri əməliyyatın SAHİBİ, digəri
    # timeout müdaxiləsi hüququdur.
    "VERIFICATION_TIMEOUT": ("can_verify_returns", "can_approve_dual_control_override"),
    "CHECK_IN_TIMEOUT": ("can_verify_returns", "can_approve_dual_control_override"),
    # `leave_verification.override_return_time`: bildiriş İKİNCİ TƏSDİQ tələb
    # edir. `schema.sql` §22 flag təsvirini birbaşa yazır: "30+ dəqiqəlik vaxt
    # düzəlişinə ikinci təsdiq (HR_Admin/CEO)".
    "DUAL_CONTROL_PENDING": ("can_approve_dual_control_override",),
    # `dual_control_guard`: şərh "bütün adminlərə" deyir. Deadlock-un YEGANƏ
    # həlli təsdiq flag-ini kiməsə vermək olduğu üçün auditoriya icazə paylaya
    # bilən roldur — `can_control_user_permissions` (Admin/CEO/Root, §23).
    "DUAL_CONTROL_DEADLOCK_RISK": ("can_control_user_permissions",),
    # `fine_management.submit_appeal`: şərhdə flag adbaad yazılıb.
    "FINE_APPEAL_PENDING": ("can_approve_leave_appeal",),
    # `fine_management.expire_stale` (M-6): "72 saat keçdi, etiraza hələ
    # baxılmayıb" xəbərdarlığı. Auditoriya `FINE_APPEAL_PENDING` ilə EYNİDİR —
    # sətri görməli olan şəxs onu QAPADA bilən şəxsdir. Başqa auditoriya
    # seçmək (məs. `can_view_audit_logs`) xəbərdarlığı seyrçiyə göstərib
    # məsul şəxsdən gizlədərdi.
    "FINE_APPEAL_SLA_BREACH": ("can_approve_leave_appeal",),
    # `fine_management.approve` (M-6): cərimə ARTIQ export olunub, sonra
    # ləğv/azaldılıb. Düzəlişi apara bilən yeganə şəxs hesabat faylını
    # göndərəndir — `can_export_reports`. Etiraza qərar verən HR_Admin-in
    # özü bunu görməsi kifayət deyil: fayl onun əlində deyil.
    "FINE_REVERSED_AFTER_EXPORT": ("can_export_reports",),
    # `shift_scheduling.request_swap`: şərhdə flag adbaad yazılıb.
    "SHIFT_SWAP_PENDING": ("can_approve_shift_swap",),
    # `storage/quota_monitor`: şərhdə marşrut adbaad yazılıb.
    "DRIVE_QUOTA": ("can_manage_drive_connection",),
    # `morning_check_in.reject` və `leave_verification.request_leave`:
    # hər ikisinin şərhi "HR_Admin + Store Manager" deyir. §23-də bu iki rolun
    # kəsişməsindəki və işçi davranışına aid olan flag `can_view_employee_reports`-dur
    # ("fərdi performans/cərimə tarixçəsinə yalnız-baxış"). `Satıcı` və kamera
    # rolları onu daşımır.
    "CHECK_IN_REJECTED": ("can_view_employee_reports",),
    "MONTHLY_LEAVE_LIMIT_EXCEEDED": ("can_view_employee_reports",),
    # `authentication.EmergencyAccessRecoveryUseCase`: hazırlayıcı tərəfin
    # icra etdiyi fövqəladə giriş bərpası TƏHLÜKƏSİZLİK hadisəsidir, iş
    # bildirişi deyil. Onu görməli olan şəxs audit izini onsuz da izləyəndir
    # — `can_view_audit_logs`. Hamıya göstərmək hücum səthini genişləndirirdi:
    # adi işçiyə "kimin hansı hesaba fövqəladə giriş açdığı" məlumatı nə
    # lazımdır, nə də onunla bir şey edə bilər.
    "EMERGENCY_ACCESS_RECOVERY": ("can_view_audit_logs",),
    # `shift_scheduling._detect_conflicts`: münaqişəni yalnız cədvəli dəyişən
    # şəxs həll edə bilər (sorğunu bağlamaq / günü yenidən planlamaq), yəni
    # `ATTENDANCE_SHEET_MISMATCH` ilə eyni auditoriya — hər ikisi növbə
    # PLANI ilə faktiki vəziyyət arasındakı fərqdən doğur.
    "SHIFT_CHANGE_CONFLICT": ("can_manage_shifts",),
    # `payment_reminders.NotifierReminderSender`: lisenziya ödənişi kirayəçi
    # inzibatçısının işidir. `can_manage_license` §22-də səviyyə-1 hardlock-dur
    # (Root; CEO-ya defolt verilmir), yəni auditoriya dar və dəqiqdir.
    # E-poçt ehtiyat kanalı BU SÜZGƏCDƏN ASILI DEYİL — o, şirkət əlaqə
    # ünvanına gedir (`notifier.py` başlığı), ona görə ödəniş xəbərdarlığı
    # tətbiq daxilində darlaşsa da şirkətə çatmağa davam edir.
    "PAYMENT_REMINDER": ("can_manage_license",),
    # `daily_attendance.submit`: şərh yalnız "HR_Admin-ə xəbərdarlıq" deyir.
    # Uyğunsuzluq TABEL ilə NÖVBƏ PLANI arasındadır, yəni cavab verəcək şəxs
    # planın sahibidir — `can_manage_shifts` (HR_Admin-də var, Mağaza
    # Menecerində yoxdur, §23). Mağaza Meneceri tabeli ÖZÜ doldurur
    # (`can_fill_daily_attendance`); ona öz təqdim etdiyi sətir barədə
    # xəbərdarlıq göndərmək məlumat vermir.
    "ATTENDANCE_SHEET_MISMATCH": ("can_manage_shifts",),
    # `overtime_tracking.record_for_day`: sətir bir işçinin NEÇƏ SAAT işlədiyini
    # elan edir — fərdi əmək məlumatıdır. `ATTENDANCE_SHEET_MISMATCH`-dan fərqli
    # olaraq cavab verəcək şəxs plan sahibi deyil, işçi hesabatlarına baxandır:
    # aşımın həlli ya növbənin qısaldılması, ya da əlavə iş vaxtının rəsmi
    # sənədləşdirilməsidir və hər ikisi HR-ın işidir (`can_view_employee_reports`
    # — HR_Admin/CEO-da var, `Satıcı`-da yoxdur, §23).
    "OVERTIME_NORM_EXCEEDED": ("can_view_employee_reports",),
    # `employee_documents.notify_expiring_documents`: gecəlik iş — 30/14/7 gün
    # qalanda bitmə xəbərdarlığı (#17, kompasos11.md Faza 7). Auditoriya
    # sənədi İDARƏ EDƏ BİLƏN roldur, sadəcə görəndir — `can_manage_employee_documents`
    # (migrations/021 flag təsviri: "sənəd/müqavilə qeydlərini yaratmaq, bitmə
    # tarixini izləmək"). Bloklama xəbərdarlığından fərqli olaraq (o, ekran
    # qarşısındakı admin üçündür və bildiriş kanalını doldurmur — bax
    # `shift_scheduling._document_conflicts`), bu, PLANLAŞDIRILMIŞ işdir və
    # heç kim ekranda deyil, ona görə bildiriş MƏCBURİDİR.
    "EMPLOYEE_DOCUMENT_EXPIRING": ("can_manage_employee_documents",),
    # `AttritionRiskUseCase._notify_high_risk`: yüksək risk aşkarlananda İKİ
    # bildiriş gedir — ƏVVƏLCƏ işçinin Store Manager-inə (ŞƏXSİ sətir,
    # `recipient_id` dolu, bu cədvəldən ASILI DEYİL), SONRA HR_Admin-ə
    # (tenant-broadcast). Auditoriya elə bu balı GÖRMƏK səlahiyyətinin ÖZÜdür
    # — `can_view_attrition_risk` (migrations/021: "defolt heç bir operativ
    # rola verilmir, yalnız HR_Admin/CEO/Root"). Store Manager bu flag-i
    # DAŞIMASA da öz işçisi barədə ŞƏXSİ sətri görür — bu, cədvəldəki
    # süzgəcdən deyil, şəxsi bildiriş qaydasından gəlir (bax fayl başlığı
    # "ŞƏXSİ SƏTİR").
    "ATTRITION_RISK_HIGH": ("can_view_attrition_risk",),
    # `FieldReportUseCase.submit`: insident kateqoriyası `field_report_
    # categories.route_to_role`-a görə marşrutlanır (#27). Marşrut ROLA
    # göstərir və həmin roldakı işçilərə ŞƏXSİ sətir gedir — o, bu cədvəldən
    # ASILI DEYİL (bax fayl başlığı "ŞƏXSİ SƏTİR"). Bu sətir yalnız EHTİYAT
    # yolu qapayır: marşrut boşdursa və ya həmin rolda AKTİV işçi yoxdursa,
    # bildiriş tenant-broadcast kimi gedir və süzgəcsiz qalsaydı `Satıcı`
    # "mağazada oğurluq şübhəsi var" sətrini görərdi.
    #
    # AUDİTORİYA `can_report_incident` DEYİL — o, BÜTÜN rollara verilib
    # (migrations/038, Tələ 3), yəni süzgəc kimi heç nə etməzdi. Hesabatı
    # HƏLL EDƏN tərəf lazımdır: `can_conduct_store_audit` migrations/038-də
    # DƏQİQ Root/CEO/Admin/HR_Admin-ə verilir — seed edilmiş marşrut
    # dəyərləri (`ADMIN`, `HR_ADMIN`) məhz bu dördlüyün içindədir.
    # `MAGAZA_MENECERI` bilərəkdən kənardadır (038: öz mağazasını özü auditə
    # çəkməsi maraq ziddiyyətidir) və eyni səbəb insidentə də aiddir.
    "FIELD_REPORT_ROUTED": ("can_conduct_store_audit",),
    # `FieldReportUseCase.notify_overdue_audits`: gecəlik iş — audit intervalı
    # keçmiş filiallar (#26). Konkret alıcısı yoxdur (planlayıcı çağırır),
    # ona görə tenant-broadcast-dır və auditoriyası auditi APARA BİLƏN
    # roldur — bildirişin tələb etdiyi əməliyyatı qoruyan flag-in ÖZÜ.
    "FIELD_REPORT_AUDIT_DUE": ("can_conduct_store_audit",),
    # `ExecutiveDigestUseCase._deliver` (#30, kompas1.md Faza 6): rola marşrutlanmış
    # sətir ŞƏXSİ olduğu üçün bu cədvəldən ASILI DEYİL (bax fayl başlığı "ŞƏXSİ
    # SƏTİR"). BU sətir YALNIZ EHTİYAT yolunu qapayır: `recipient_role`
    # boşdursa/həmin roldan aktiv işçi yoxdursa, xülasə tenant-broadcast kimi
    # gedir. Auditoriya `can_configure_executive_digest`-dir — CƏMİ Root/CEO
    # (migrations/038, ROOT_CEO hardlock səviyyə 2): şəbəkə-miqyaslı cərimə/
    # istisna/overtime/turnover rəqəmləri EHTİYAT yolunda belə YALNIZ xülasəni
    # KONFİQURASİYA EDƏ BİLƏN roldadır — süzgəcsiz sətir FAIL-OPEN olardı və
    # hər `Satıcı` bu göstəriciləri görərdi.
    "EXECUTIVE_DIGEST_DELIVERED": ("can_configure_executive_digest",),
    # `fine_review.MonthlyFineReviewUseCase._record` (DEEP-GAP D2): işçi nəşr
    # ANINDA deaktivdirsə cərimə `PENDING_REVIEW`-də saxlanılır və HR əl ilə
    # qərar verməlidir. Auditoriya `can_publish_fines`-dir — "[Bütün Filiallara
    # Göndər]" düyməsini basan ROL, saxlanan sətri də görməlidir; başqa rol
    # (məs. sadə HR) görsə, düyməni basa bilmədiyi üçün heç nə edə bilməzdi.
    "MONTHLY_FINES_HELD_INACTIVE_EMPLOYEE": ("can_publish_fines",),
    # `user_management.UserManagementUseCase.deactivate_employee` (DEEP-GAP
    # D2): deaktiv edilən işçinin AÇIQ (nəşr gözləyən/etirazlı) cərimələri var.
    # Auditoriya YENƏ `can_publish_fines`-dir — EYNİ SƏBƏB: bu sətirlərin
    # taleyini yalnız nəşr edə bilən rol həll edə bilər (əl ilə saxlamaq/silmək).
    "EMPLOYEE_DEACTIVATED_WITH_OPEN_FINES": ("can_publish_fines",),
    # `fine_review.MonthlyFineReviewUseCase._record` (DEEP-GAP T3): sübut
    # şəkli hələ Drive-a yüklənməmiş MANUAL_CAMERA cəriməsi nəşr edilmir.
    # Auditoriya YENƏ `can_publish_fines`-dir, LAKİN səbəb bir qədər fərqlidir:
    # sətir cərimə alan İŞÇİNİN adını daşımasa da, hansı cərimənin sübutsuz
    # qaldığını açır — bu, nəşrə qədər gizli qalmalı olan məlumatdır (`Fine.
    # is_visible_to_employee` qaydası). Süzgəcsiz sətir onu bütün filiala
    # göstərərdi.
    "MONTHLY_FINES_HELD_MISSING_EVIDENCE": ("can_publish_fines",),
    # ─────────────────────────────────────────────────────────────────────
    # `MONTHLY_FINES_PUBLISHED` BURAYA QƏSDƏN SALINMIR — ONU SÜZMƏYİN.
    # ─────────────────────────────────────────────────────────────────────
    # Bu bildiriş cərimələrin artıq GÖRÜNƏN olduğunu elan edir və 72 saatlıq
    # etiraz pəncərəsi məhz həmin andan sayılır (`fine_review.py` qəsdli
    # deviasiyası: `PENDING_REVIEW` → aylıq icmal → `PUBLISHED`). Kimsə onu
    # "menecer bildirişi" sanıb auditoriyaya bağlasa, cərimə alan işçi
    # cəriməsinin açıldığından və sayğacın başladığından XƏBƏRSİZ qalar —
    # yəni etiraz hüququ formal olaraq var, praktikada isə yoxdur. Cədvəldə
    # olmaması onu HAMIYA görünən saxlayır və bu, tələb olunan davranışdır.
}


def hidden_tenant_categories(has_flag: Callable[[str], bool]) -> frozenset[str]:
    """Aktorun GÖRMƏMƏLİ olduğu tenant səviyyəli kateqoriyalar.

    "Görünənlər" yox, "gizlədilənlər" qaytarılır və bu, qəsdəndir: sorğu
    süzgəci `category <> ALL(...)` şəklində qurulur, yəni cədvəldə OLMAYAN
    kateqoriya avtomatik görünür (fail-open, bax cədvəl başlığı). Görünənlər
    siyahısı qaytarılsaydı, hər yeni kateqoriya cədvələ yazılana qədər
    sükutla gizlənərdi.

    Args:
        has_flag: `Employee.has_permission` üzərində qurulan predikat. Domen
            burada `Employee`-ni birbaşa QƏBUL ETMİR — `value_objects` qatı
            `entities` qatından asılı olmamalıdır (əks istiqamət artıq var).
            Predikat həm də fərdi override-ları avtomatik nəzərə alır.
    """
    return frozenset(
        category
        for category, flags in TENANT_NOTIFICATION_AUDIENCE.items()
        if not any(has_flag(flag) for flag in flags)
    )


def email_subject(category: str, title_az: str) -> str:
    """E-poçt mövzusu — qutuda süzgəclənə bilsin deyə prefiks daşıyır.

    Prefiks olmadan bu mesajlar admin-in qutusunda digər yazışmalarla
    qarışardı; süzgəc qurmaq mümkün olmazdı və nəticədə spesifikasiyanın
    məqsədi ("gözdən qaçmasın") pozulardı.
    """
    try:
        label = NotificationCategory(category.strip().upper()).label_az
    except ValueError:
        label = category.strip() or "Bildiriş"
    return f"[KompasOS] {label}: {title_az}".strip()


def email_body(title_az: str, body_az: str, *, tenant_name: str = "") -> str:
    """E-poçt mətni — sadə mətn, HTML yoxdur.

    HTML şablon PII-ni gizlətmir, əvəzində yalnız render problemləri gətirir
    (kiril/Azərbaycan hərfləri, mobil qutular, spam filtrləri). Bildirişin
    məqsədi diqqət çəkməkdir, dizayn deyil.
    """
    header = f"{tenant_name} — {title_az}" if tenant_name else title_az
    return (
        f"{header}\n"
        f"{'-' * min(len(header), 60)}\n\n"
        f"{body_az}\n\n"
        "Bu bildiriş KompasOS tərəfindən avtomatik göndərilib.\n"
        "Ətraflı məlumat üçün proqramı açın."
    )


__all__ = [
    "ALWAYS_CRITICAL_CATEGORIES",
    "TENANT_NOTIFICATION_AUDIENCE",
    "NotificationCategory",
    "email_body",
    "email_subject",
    "hidden_tenant_categories",
    "is_critical_category",
]
