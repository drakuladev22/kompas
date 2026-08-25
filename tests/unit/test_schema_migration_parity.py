"""`schema.sql` ↔ miqrasiya paritesi — eyni obyekt İKİ yerdə EYNİ olmalıdır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU QAPI VAR
──────────────────────────────────────────────────────────────────────────────
DB-1 konsolidasiya auditi belə bir qüsur tapdı: `enforce_anti_fraud_segregation()`
miqrasiya 013-də prioritet-əsaslı qadağa ilə gücləndirilmiş, 048-də həddi
yenilənmiş, lakin `schema.sql`-dəki nüsxə HEÇ VAXT yenilənməmişdi.

Nəticə sükutlu idi və yalnız quraşdırma YOLUNDAN asılı görünürdü:

  * tam miqrasiya zənciri tətbiq olunmuş baza → GÜCLÜ qapı (düzgün);
  * `schema.sql` ilə təmiz quraşdırma       → ZƏİF qapı — "satıcı-pilləli"
    custom rol bütün anti-fraud flag-lərini DB səviyyəsində qəbul edərdi.

Domen qatı hər iki halda bloklayırdı, yəni müdafiənin İKİNCİ qatı bir yolda
YOX idi. CLAUDE.md §5 məhz bunu qadağan edir: «Hər qayda İKİ yerdə var —
domendə və DB trigger-ində. Birini dəyişəndə DİGƏRİ də dəyişməlidir.»

Heç bir mövcud test bunu tuta bilmirdi, çünki `database/tests/test_guards.sql`
FAKTİKİ bazaya qarşı işləyir — yəni miqrasiyalar tətbiq olunduqdan SONRAKI
vəziyyəti ölçür və `schema.sql`-in öz mətnini heç vaxt görmür.

──────────────────────────────────────────────────────────────────────────────
NƏ ÖLÇÜLÜR
──────────────────────────────────────────────────────────────────────────────
Hər obyekt (funksiya / indeks / cədvəl) HƏM `schema.sql`-də, HƏM də ən azı bir
miqrasiyada təyin olunubsa, `schema.sql`-dəki tərif SONUNCU miqrasiyanınkı ilə
üst-üstə düşməlidir. Fərq qəsdlidirsə `INTENTIONAL_DIVERGENCE`-ə SƏBƏBİ İLƏ
yazılır — yəni fərq görünməz qalmır, qərara çevrilir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
_SCHEMA: Final = _REPO_ROOT / "database" / "schema.sql"
_MIGRATIONS: Final = _REPO_ROOT / "database" / "migrations"

#: Fərqi QƏSDLİ olan obyektlər: ad → səbəb.
#:
#: Siyahıya əlavə etmək bir QƏRARDIR: "bu iki tərif fərqlidir və bu, düzgündür".
#: Səbəb yazılmasa qapı mənasını itirər — növbəti oxucu fərqin unudulmuş, yoxsa
#: seçilmiş olduğunu bilməzdi.
INTENTIONAL_DIVERGENCE: Final[dict[str, str]] = {
    "idx_notifications_email_pending": (
        "007 indeksi `email_attempts` + `email_next_attempt_at` sütunları ilə "
        "yenidən qurur, həmin sütunları isə ELƏ 007 əlavə edir. Bazis sxem "
        "onları ehtiva etmir, yəni tərif orada dəyişə BİLMƏZ — fərq qatlanma "
        "nizamının nəticəsidir."
    ),
}

#: D4 (DEEP-GAP dövrə auditi): miqrasiyada YARADILIB, `schema.sql`-ə HEÇ VAXT
#: KÖÇÜRÜLMƏYƏN obyektlər — ad → səbəb.
#:
#: `test_shared_objects_are_defined_identically` YALNIZ HƏR İKİ tərəfdə DƏ
#: mövcud olan adları müqayisə edir (`_pairs()`-in `if name in latest` şərti);
#: obyekt miqrasiyada yaranıb bazis sxemə köçürülməyibsə, heç vaxt həmin
#: müqayisəyə DÜŞMÜR — məhz bu boşluqda `enforce_position_flag_hierarchy()`
#: (046), TIME-1 (062) və `enforce_flag_attributes_immutable()` (013) tapıldı
#: — üçü də bu dövrədə `schema.sql`-ə köçürülüb (§18/etiraz pəncərəsi
#: bölmələri). Bu siyahıya əlavə etmək İKİ yoldan biri deməkdir: (a) obyekt
#: bazis sxemə köçürülüb — sətir SİLİNİR; (b) köçürmə QƏSDƏN edilmir —
#: sətir SƏBƏBLƏ QALIR.
#:
#: ──────────────────────────────────────────────────────────────────────
#: QALAN ~110 AD: D4-DƏN AYRI, DAHA BÖYÜK BİR TAPINTI
#: ──────────────────────────────────────────────────────────────────────
#: Bu test yazılarkən üzə çıxdı: `database/migrations/*.sql`-in yaratdığı
#: 39 CƏDVƏL (`announcements`, `field_reports`, `registered_devices`,
#: `tenant_branding`, `telegram_config`, s.) `schema.sql`-ə HEÇ VAXT
#: köçürülməyib — CLAUDE.md §7-nin "tək başına tam quraşdırma" iddiasına
#: baxmayaraq. Bu, D4-ün ORİJİNAL tapıntısı ilə EYNİ SİNİFDƏN (miqrasiyada
#: yaranıb bazis sxemə köçürülməyən obyekt), lakin miqyası 39 cədvəl + bu
#: cədvəllərə bağlı ~100 funksiya/trigger-dir — TƏK agentin bu turda təhlükəsiz
#: həll edə biləcəyi ölçüdən BÖYÜKDÜR (səhv sıra/FK asılılığı riski). Komanda
#: rəhbərinə AYRICA hesabat verilib. Aşağıdakı QRUPLAR bu tapıntının
#: FUNCTION/TRIGGER təzahürüdür:
#:
#:   1) `seed_*_for_new_tenant` / `trg_seed_*` (~68 ad) — BU QRUP HƏQİQƏTƏN
#:      QƏSDLİDİR (D4-dən fərqli olaraq): migrations/062 başlığı ("032/060
#:      naxışı") açıq yazır ki, `seed_tenant_defaults()` YENİ limit qrupu
#:      əlavə olunanda YENİLƏNMİR — onun əvəzinə hər miqrasiya öz AFTER
#:      INSERT ON license_tenants trigger-ini yaradır. `provisioning.py`
#:      (`base_schema_sql()` + BÜTÜN miqrasiyalar ardıcıl) real quraşdırma
#:      yolu olduğu üçün bu trigger-lər YENƏ işə düşür — YALNIZ "schema.sql
#:      tək başına, miqrasiyasız" ssenarisində yeni tenant bu limit qrupunu
#:      qaçırar.
#:   2) 39 çatışmayan cədvələ bağlı `trg_*_updated`/`enforce_*`/`cron_prune_
#:      check_ins` (~38 ad) — cədvəlin ÖZÜ yoxdursa trigger TƏBİİ OLARAQ da
#:      yoxdur; kök səbəb #1-dəki 39-cədvəl tapıntısıdır.
#:   3) `enforce_face_exemption_compensation()`/`trg_dual_control_
#:      compensation_lock` (SEC-020) — `feature_toggles` (mövcuddur) ÜZƏRİNDƏ
#:      DAYANIR, lakin gövdəsi `face_control_exemptions`-a (YOX) SORĞU
#:      göndərir; cədvəlsiz köçürmə BÜTÜN `feature_toggles` yazılarını
#:      runtime xətası ilə ÇÖKDÜRƏRDİ — #1-dəki tapıntıdan asılıdır, TƏK
#:      başına köçürülə BİLMƏZ.
#:   4) `license_scope_tenant_id()` (migrations/006, Master Panel RLS) —
#:      `license_tenants`/`crash_reports` mövcuddur, lakin siyasət
#:      `tenant_check_ins`-ə (YOX) də bağlıdır və PostgREST-only JWT claim
#:      oxuyur (`request.jwt.claims`) — psycopg-yalnız `KOMPASOS_PRIVATE_
#:      SERVER_DSN` yolunda mənası fərqlidir, AYRICA təhlil tələb edir.
_MISSING_TABLE_GROUP: Final[dict[str, str]] = {
    "cron_prune_check_ins": "tenant_check_ins",
    "enforce_announcement_target_scope": "announcement_targets",
    "trg_announcement_target_scope": "announcement_targets",
    "trg_announcements_updated": "announcements",
    "trg_annual_leave_balances_updated": "annual_leave_balances",
    "trg_annual_leave_requests_updated": "annual_leave_requests",
    "enforce_app_job_run_transition": "app_scheduled_job_runs",
    "trg_app_job_run_transition": "app_scheduled_job_runs",
    "trg_app_job_runs_updated": "app_scheduled_job_runs",
    "trg_attrition_scores_updated": "attrition_risk_scores",
    "trg_behavior_baseline_updated": "employee_behavior_baseline",
    # v2backlog.md (miqrasiyalar 088–091) — YENİ cədvəllər, hələ `schema.sql`-ə
    # köçürülməyib. Eyni sinifdən: D4-ün 39-cədvəl tapıntısının davamıdır.
    "trg_campaign_periods_updated": "campaign_periods",
    "trg_checklist_item_templates_updated": "checklist_item_templates",
    "trg_daily_break_usage_updated": "daily_break_usage",
    "trg_drive_connections_updated": "drive_connections",
    "trg_employee_documents_updated": "employee_documents",
    # v2backlog.md (miqrasiya 088) — bax yuxarıdakı campaign_periods/
    # checklist_item_templates şərhi, EYNİ səbəb.
    "trg_server_created_at_offboarding": "employee_offboarding_checklists",
    "trg_offboarding_checklists_updated": "employee_offboarding_checklists",
    "trg_offboarding_items_updated": "employee_offboarding_checklist_items",
    "trg_server_created_at_transfer_requests": "employee_transfer_requests",
    "trg_exception_sources_updated": "exception_sources",
    "trg_exceptions_updated": "exceptions",
    "trg_executive_digest_updated": "executive_digest_config",
    "enforce_exemption_requires_compensation": "face_control_exemptions",
    "trg_exemption_requires_compensation": "face_control_exemptions",
    "trg_face_exemptions_updated": "face_control_exemptions",
    "trg_face_store_scope_updated": "face_control_store_scope",
    "trg_field_report_categories_updated": "field_report_categories",
    "trg_field_report_items_updated": "field_report_checklist_items",
    "trg_field_report_types_updated": "field_report_types",
    "trg_field_reports_updated": "field_reports",
    "enforce_open_shift_claim_transition": "open_shift_postings",
    "trg_open_shift_claim_transition": "open_shift_postings",
    "trg_open_shift_postings_updated": "open_shift_postings",
    "trg_overtime_log_updated": "overtime_log",
    "trg_performance_reviews_updated": "performance_reviews",
    "trg_pos_thresholds_updated": "pos_permission_thresholds",
    "trg_registered_devices_updated": "registered_devices",
    "trg_server_created_at_branding": "tenant_branding",
    "trg_server_created_at_devices": "registered_devices",
    "trg_staffing_suggestions_updated": "staffing_pattern_suggestions",
    # AF-2 — üz kanalının AYRI sayğacı (miqrasiya 086). PIN əkizi ilə eyni
    # qrupdadır: hər ikisinin CƏDVƏLİ `schema.sql`-də ÜMUMİYYƏTLƏ yoxdur.
    "enforce_store_face_throttle_lockout": "store_face_throttle",
    "trg_store_face_throttle_lockout": "store_face_throttle",
    "enforce_store_pin_throttle_lockout": "store_pin_throttle",
    "trg_store_pin_throttle_lockout": "store_pin_throttle",
    "trg_store_templates_updated": "store_templates",
    # v2backlog.md (miqrasiya 104) — bax `trg_campaign_periods_updated` şərhi,
    # EYNİ səbəb: `whats_new_entries` cədvəli də hələ `schema.sql`-də deyil.
    "trg_whats_new_updated": "whats_new_entries",
    # v2backlog.md (miqrasiya 090) — bax `trg_campaign_periods_updated` şərhi,
    # EYNİ səbəb. Funksiya AF-2/PIN cütü ilə EYNİ naxışdadır (`enforce_*` +
    # `trg_*`, ikisi də CƏDVƏLİ `schema.sql`-də olmayan `support_chat_
    # throttle`-a bağlıdır).
    "enforce_support_chat_throttle_lockout": "support_chat_throttle",
    "trg_support_chat_throttle_lockout": "support_chat_throttle",
    "trg_telegram_config_updated": "telegram_config",
    "trg_tenant_branding_updated": "tenant_branding",
    # v2backlog.md (miqrasiya 091) — bax `trg_campaign_periods_updated` şərhi,
    # EYNİ səbəb.
    "trg_webhook_endpoints_updated": "webhook_endpoints",
}

#: `seed_*_for_new_tenant` funksiyaları ilə onların `trg_seed_*` trigger-ləri
#: — ad cütü DÜZ NAXIŞLA (`seed_X_for_new_tenant` ↔ `trg_seed_X`) uyğun
#: gəlmir (məs. `seed_branding_for_new_tenant` ↔ `trg_seed_tenant_branding`),
#: ona görə HƏR İKİSİ EYNİ ÜMUMİ səbəblə, ayrıca siyahıdan doldurulur.
_SEED_TRIGGER_REASON: Final = (
    "032/060 naxışı (062 başlığı): `seed_tenant_defaults()` yeni limit qrupu "
    "üçün YENİLƏNMİR, əvəzinə bu miqrasiyanın öz `AFTER INSERT ON "
    "license_tenants` trigger-i yeni tenant-ı seedləyir. `provisioning.py` "
    "sıralı tətbiqdə (schema.sql + BÜTÜN miqrasiyalar) bu YENƏ işə düşür — "
    "yalnız 'schema.sql tək başına' ssenarisində yeni tenant bu limit "
    "qrupunu qaçırar. D4-dən AYRI tapıntı, bax modul-səviyyəli şərh."
)

MISSING_FROM_SCHEMA: Final[dict[str, str]] = (
    {
        name: f"Cədvəlin ÖZÜ (`{table}`) `schema.sql`-də yoxdur — D4-dən AYRI, "
        "daha böyük 39-cədvəl tapıntısının nəticəsi (bax modul-səviyyəli şərh, "
        "qrup #2/#3/#4). Trigger/funksiya TƏBİİ OLARAQ da yoxdur."
        for name, table in _MISSING_TABLE_GROUP.items()
    }
    | {
        "trg_dual_control_compensation_lock": (
            "SEC-020: `feature_toggles` (mövcuddur) üzərindədir, LAKİN gövdəsi "
            "`face_control_exemptions`-a (YOX) sorğu göndərir — cədvəlsiz "
            "köçürmə BÜTÜN `feature_toggles` yazılarını runtime xətası ilə "
            "çökdürərdi. #3-cü qrup, bax modul-səviyyəli şərh."
        ),
        "enforce_face_exemption_compensation": (
            "SEC-020: yuxarıdakı `trg_dual_control_compensation_lock`-un funksiyası — EYNİ səbəb."
        ),
        "license_scope_tenant_id": (
            "Master Panel RLS (migrations/006): `license_tenants`/`crash_"
            "reports` mövcuddur, lakin siyasət `tenant_check_ins`-ə (YOX) də "
            "bağlıdır və PostgREST-only JWT claim oxuyur — psycopg-yalnız "
            "`KOMPASOS_PRIVATE_SERVER_DSN` yolunda mənası fərqlidir, AYRICA "
            "təhlil tələb edir. #4-cü qrup, bax modul-səviyyəli şərh."
        ),
        "enforce_server_employee_deactivated_at": (
            "TIME-1 (migrations/096): `employees.deactivated_at`-ı `is_active` "
            "keçidinə görə SERVER vaxtı ilə möhürləyir/sıfırlayır — "
            "`v2backlog.md` Faza 3.2 retensiya hesablamasının lövbəri. "
            "`schema.sql` QƏSDƏN yenilənmir (migrasiyanın ÖZÜ başlığı): sütun "
            "artıq bazis sxemdə var, YALNIZ YENİ trigger əlavə olunur — "
            '`CLAUDE.md` §7 "qayda qatlanmır" prinsipinə görə köçürmə '
            "TƏLƏB OLUNMUR, çünki bu, mövcud qaydanın YENİDƏN yazılması "
            "DEYİL, tamam YENİ obyektdir."
        ),
        "trg_server_employee_deactivated_at": (
            "Yuxarıdakı `enforce_server_employee_deactivated_at`-ın trigger-i — EYNİ səbəb."
        ),
        "trg_server_created_at_handoff_notes": (
            "TIME-1 (migrations/099): `shift_handoff_notes.created_at`-ı mövcud "
            "ORTAQ funksiya `enforce_server_created_at()` ilə server vaxtına "
            "möhürləyir — təhvil qeydini İŞÇİ yazır və «mən bunu vaxtında "
            "təhvil vermişdim» mübahisəsi üçün vaxt-hövməsi SÜBUT olunmalıdır. "
            "`schema.sql` QƏSDƏN yenilənmir: bu, mövcud qaydanın YENİDƏN "
            "yazılması DEYİL, yeni cədvələ TAM YENİ trigger bağlantısıdır "
            "(096-nın `trg_server_employee_deactivated_at` pretsedenti)."
        ),
        "trg_server_created_at_break_glass": (
            "TIME-1 (migrations/099): `break_glass_grants.created_at`-ı eyni "
            "ortaq funksiya ilə server vaxtına möhürləyir — fövqəladə giriş "
            "səlahiyyətinin VAXTI hüquqi-audit əsəridir və client saatından "
            "asılı OLA BİLMƏZ. 096/099 pretsedenti: yeni cədvəl, yeni trigger, "
            "ortaq funksiya toxunulmadan."
        ),
    }
    | dict.fromkeys(
        (
            name
            for name in (
                "seed_annual_leave_limits_for_new_tenant",
                "seed_application_layer_limits_for_new_tenant",
                "seed_attendance_counting_limits_for_new_tenant",
                "seed_attrition_risk_limits_for_new_tenant",
                "seed_behavior_baseline_limits_for_new_tenant",
                "seed_br_limits_for_new_tenant",
                "seed_branding_for_new_tenant",
                "seed_break_parameters_for_new_tenant",
                "seed_bulk_operations_limits_for_new_tenant",
                "seed_communication_performance_limits_for_new_tenant",
                "seed_device_limits_for_new_tenant",
                "seed_domain_value_object_limits_for_new_tenant",
                "seed_dual_control_timeout_for_new_tenant",
                "seed_employee_document_expiry_limits_for_new_tenant",
                "seed_erp_connector_limits_for_new_tenant",
                "seed_exception_limits_for_new_tenant",
                "seed_executive_digest_limits_for_new_tenant",
                "seed_export_preflight_limits_for_new_tenant",
                "seed_face_control_limits_for_new_tenant",
                "seed_field_report_limits_for_new_tenant",
                # Miqrasiya 084 — dörd yeni Root açarı (saxlama müddəti, üz
                # qeydiyyatı möhləti, etiraz eskalasiyası, nəşr gecikməsi).
                "seed_hr_and_retention_limits_for_new_tenant",
                # Miqrasiya 095 — `v2backlog.md` Faza 3.2/3.5 üçün iki yeni
                # Root açarı (deaktiv işçi retensiyası, tövsiyə bonusu).
                "seed_hr_lifecycle_v2_limits_for_new_tenant",
                # Miqrasiya 102 — `v2backlog.md` Faza 6.5 üçün «əhəmiyyətli
                # fərq» həddi (iş-yükü ədalətliliyi widget-i).
                "seed_analytics_limits_for_new_tenant",
                # Miqrasiya 103 — `v2backlog.md` Faza 7 üçün davranış-cüt
                # açarları (korrelyasiya-həddi + min nümunə + sinxron pəncərə).
                "seed_behavior_pair_limits_for_new_tenant",
                # Miqrasiya 108 — `v2backlog.md` Faza 6.4-ün tamamlanması:
                # kampaniya günlərinin növbə təklifindəki çəkisi.
                "seed_campaign_weight_limit_for_new_tenant",
                "seed_history_page_size_limits_for_new_tenant",
                "seed_infrastructure_runtime_limits_for_new_tenant",
                "seed_labor_and_staffing_limits_for_new_tenant",
                "seed_multi_store_benchmark_limits_for_new_tenant",
                "seed_open_shift_market_limits_for_new_tenant",
                "seed_overtime_limits_for_new_tenant",
                "seed_pin_throttle_limits_for_new_tenant",
                "seed_pos_threshold_limits_for_new_tenant",
                "seed_presentation_runtime_limits_for_new_tenant",
                "seed_report_range_limits_for_new_tenant",
                # Miqrasiya 104 — `v2backlog.md` Faza 8.1 üçün interfeys-dili
                # açarı (hazırda yalnız «az»; rus tərcüməsi QADAĞDIR).
                "seed_ui_language_limit_for_new_tenant",
                # Miqrasiya 100 — `v2backlog.md` Faza 5 üçün doqquz yeni
                # Root açarı (offline bufer, təhvil qeydi, break-glass).
                "seed_resilience_limits_for_new_tenant",
                # Miqrasiya 101 — öz-düzəliş sorğusunun sui-istifadə tavan
                # cütü (`v2backlog.md` Faza 4.2; 084 pretsedenti: seed
                # unudulması YENİ miqrasiya ilə bağlanır, 097 redaktə OLUNMUR).
                "seed_self_correction_limits_for_new_tenant",
                "seed_scheduler_limits_for_new_tenant",
                "seed_server_time_limits_for_new_tenant",
                "seed_session_limits_for_new_tenant",
                # Miqrasiya 107 — dəstək-chat sürət sayğacı açarları (Faza 12.1).
                "seed_support_chat_throttle_limits_for_new_tenant",
                "seed_telegram_limits_for_new_tenant",
                "seed_ui_surface_limits_for_new_tenant",
                "trg_seed_annual_leave_limits",
                "trg_seed_analytics_limits",
                "trg_seed_application_layer_limits",
                "trg_seed_attendance_counting_limits",
                "trg_seed_attrition_risk_limits",
                "trg_seed_behavior_baseline_limits",
                "trg_seed_behavior_pair_limits",
                "trg_seed_campaign_weight_limit",
                "trg_seed_br_limits",
                "trg_seed_break_parameters",
                "trg_seed_bulk_operations_limits",
                "trg_seed_communication_performance_limits",
                "trg_seed_device_limits",
                "trg_seed_domain_value_object_limits",
                "trg_seed_dual_control_timeout",
                "trg_seed_employee_document_expiry_limits",
                "trg_seed_erp_connector_limits",
                "trg_seed_exception_limits",
                "trg_seed_executive_digest_limits",
                "trg_seed_export_preflight_limits",
                "trg_seed_face_control_limits",
                "trg_seed_hr_and_retention_limits",
                "trg_seed_hr_lifecycle_v2_limits",
                "trg_seed_field_report_limits",
                "trg_seed_history_page_size_limits",
                "trg_seed_infrastructure_runtime_limits",
                "trg_seed_labor_and_staffing_limits",
                "trg_seed_multi_store_benchmark_limits",
                "trg_seed_open_shift_market_limits",
                "trg_seed_overtime_limits",
                "trg_seed_pin_throttle_limits",
                "trg_seed_pos_threshold_limits",
                "trg_seed_presentation_runtime_limits",
                "trg_seed_report_range_limits",
                "trg_seed_resilience_limits",
                "trg_seed_self_correction_limits",
                "trg_seed_scheduler_limits",
                "trg_seed_server_time_limits",
                "trg_seed_session_limits",
                "trg_seed_support_chat_throttle_limits",
                "trg_seed_telegram_limits",
                "trg_seed_tenant_branding",
                # Miqrasiya 104 — interfeys dili açarı (Faza 8.1).
                "trg_seed_ui_language_limits",
                "trg_seed_ui_surface_limits",
            )
        ),
        _SEED_TRIGGER_REASON,
    )
)

#: Yalnız bu ad növləri müqayisə olunur. `CREATE TABLE` da daxildir, çünki
#: `monthly_fine_review_batches` hər iki yerdə tam təriflə mövcuddur.
#:
#: D4 (DEEP-GAP dövrə auditi): `plpgsql\s*;` DEQİQ sonluq tələb edirdi —
#: `$$ LANGUAGE plpgsql IMMUTABLE;`/`STABLE;` (`calculate_leave_penalty`,
#: schema.sql:798; başqa bir funksiya, schema.sql:3068; migrations/006:112)
#: burada UYĞUN GƏLMİR. Nəticə SƏSSİZ idi: `.*?` qeyri-acgöz olduğu üçün
#: axtarış NÖVBƏTİ təmiz `plpgsql;` sonluğuna qədər davam edir və aradakı
#: BİR NEÇƏ funksiyanı YANLIŞ FUNKSİYANIN gövdəsinə uddurur — onlar nə
#: `_pairs()`-də, nə YENİ `MISSING_FROM_SCHEMA` yoxlamasında DÜZGÜN
#: görünmürdü (bax `cron_prune_notifications` — D4 ilə əlavə edilib, lakin
#: bu qüsur onu `calculate_leave_penalty`-nin gövdəsinə uddurmuşdu).
#: `(?:\s+\w+)*` volatillik/təhlükəsizlik açar sözlərini (`IMMUTABLE`,
#: `STABLE`, `SECURITY DEFINER`, s.) udmadan `;`-ə qədər gedir.
_FUNCTION = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+([a-z_][a-z0-9_]*)\s*\(.*?"
    r"\$\$\s*LANGUAGE\s+plpgsql(?:\s+\w+)*\s*;",
    re.IGNORECASE | re.DOTALL,
)
_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s+(ON\s+.*?);",
    re.IGNORECASE | re.DOTALL,
)
_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s*\((.*?)\n\);",
    re.IGNORECASE | re.DOTALL,
)
#: INF2-01 (dövrə 2 audit): `CREATE TRIGGER` HANSI funksiyaya bağlandığını
#: (VƏ hansı cədvələ, hansı zamanlamada) daşıyır — bu, `_FUNCTION` regex-inin
#: GÖRMƏDİYİ bir səviyyədir: funksiyanın ÖZÜ hər iki yerdə eyni ola bilər,
#: lakin trigger onu FƏRQLİ cədvələ/hadisəyə bağlaya bilər. `DROP TRIGGER`
#: qəsdən İSTİSNADIR (bu pattern yalnız `CREATE` ilə başlayır) — `DROP
#: TRIGGER IF EXISTS ...;` ilə başlayan cütlər (013/056/063/068/072 naxışı)
#: sükutla keçilir, onların yalnız `CREATE` yarısı müqayisə olunur.
_TRIGGER = re.compile(
    r"CREATE\s+TRIGGER\s+([a-z_][a-z0-9_]*)\s+(.*?);",
    re.IGNORECASE | re.DOTALL,
)
#: Adlı `CONSTRAINT`-lər (FK/CHECK/UNIQUE `ALTER TABLE` ilə əlavə olunanlar) —
#: `_TABLE`-in `CREATE TABLE ( ... )` daxilindəki SƏTİR-daxili `CONSTRAINT`-i
#: artıq tuturdu, bu isə YARADILDIQDAN SONRA `ALTER TABLE` ilə əlavə olunan
#: (DB-1-in "qayda sonradan gücləndirildi" ssenarisinin constraint analoqu)
#: hallara aiddir.
_CONSTRAINT = re.compile(
    r"ALTER\s+TABLE\s+(?:ONLY\s+)?[a-z_][a-z0-9_]*\s+ADD\s+CONSTRAINT\s+"
    r"([a-z_][a-z0-9_]*)\s+(.*?);",
    re.IGNORECASE | re.DOTALL,
)


def _strip_comments(sql: str) -> str:
    """`--` şərhlərini atır — şərh fərqi davranış fərqi DEYİL."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _normalise(sql: str) -> str:
    """Boşluq/sətir fərqlərini silir; mətn və böyük-kiçik hərf QALIR.

    Xəta mesajları qəsdən saxlanılır: iki qapı eyni qaydanı fərqli mesajla
    ifadə edirsə, istifadəçi hansı qatın işə düşdüyünü bilməlidir.
    """
    return " ".join(_strip_comments(sql).split())


def _collect(pattern: re.Pattern[str], text: str, *, group: int = 0) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in pattern.finditer(text):
        name = match.group(1).lower()
        body = match.group(group) if group else match.group(0)
        found[name] = _normalise(body)
    return found


def _definitions(text: str) -> dict[str, str]:
    # INF2-01 (dövrə 2 audit) tapdı: `_TRIGGER` regex-i `016_appeal_window_
    # and_open_leave_parity.sql`-in ŞƏRHLƏNMİŞ (`--` ilə başlayan), YALNIZ
    # illüstrativ DOWN-nümunəsindəki `CREATE TRIGGER trg_fine_appeal_window
    # BEFORE INSERT ON fines` sətrini HƏQİQİ tərif kimi tutdu — çünki
    # `_strip_comments()` yalnız MATCH TAPILANDAN SONRA, hər body üzərində
    # AYRICA çağırılırdı, `finditer` isə RAW (şərhli) mətndə axtarırdı.
    # Nəticə: fayl sırasına görə bu SAXTA uyğunluq HƏQİQİ (sətir 85-86)
    # tərifi SİLİRDİ (`_collect`-in `found[name] = ...` son-udan-udur
    # naxışı). Düzəliş: şərhlər `finditer`-dən ƏVVƏL, BÜTÜN mətndən
    # çıxarılır — `_FUNCTION`/`_INDEX`/`_TABLE` da EYNİ zəifliyi daşıyırdı,
    # sadəcə heç bir mövcud şərh onların formasına düşmürdü (indiyədək).
    stripped = _strip_comments(text)
    return {
        **_collect(_FUNCTION, stripped),
        **_collect(_INDEX, stripped, group=2),
        **_collect(_TABLE, stripped, group=2),
        **_collect(_TRIGGER, stripped),
        **_collect(_CONSTRAINT, stripped),
    }


def _function_and_trigger_names(text: str) -> set[str]:
    """D4: `_definitions()`-dən DAR — YALNIZ FUNCTION/TRIGGER adları.

    Cədvəl/indeks/constraint BURAYA DAXİL DEYİL — komanda rəhbərinin D4
    tapşırığı qəsdən bu ikisinə məhdudlaşdırılıb (miqrasiyaların böyük
    əksəriyyəti `ALTER TABLE ADD COLUMN`-dır və bazis sxemə köçürülmür,
    CLAUDE.md §7: "schema.sql miqrasiya SÜTUNLARINI ehtiva etmir" — bu,
    QƏSDLİ dizayndır, D4 kimi tapılmamış qüsur DEYİL).
    """
    stripped = _strip_comments(text)
    return set(_collect(_FUNCTION, stripped)) | set(_collect(_TRIGGER, stripped))


def _migration_only_function_and_trigger_names() -> set[str]:
    """Miqrasiyada YARADILIB, `schema.sql`-ə HEÇ VAXT köçürülməyən adlar."""
    schema_names = _function_and_trigger_names(
        _SCHEMA.read_text(encoding="utf-8", errors="replace")
    )
    migration_names: set[str] = set()
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        migration_names |= _function_and_trigger_names(
            path.read_text(encoding="utf-8", errors="replace")
        )
    return migration_names - schema_names


def _pairs() -> list[tuple[str, str, str, str]]:
    """(ad, schema.sql tərifi, sonuncu miqrasiya adı, onun tərifi)."""
    schema = _definitions(_SCHEMA.read_text(encoding="utf-8", errors="replace"))

    latest: dict[str, tuple[str, str]] = {}
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        for name, body in _definitions(path.read_text(encoding="utf-8", errors="replace")).items():
            latest[name] = (path.name, body)

    return [
        (name, schema[name], latest[name][0], latest[name][1])
        for name in sorted(schema)
        if name in latest
    ]


def test_shared_objects_are_defined_identically() -> None:
    """İki yerdə təyin olunan hər obyekt EYNİ olmalıdır (və ya siyahıda)."""
    drifted = [
        (name, source)
        for name, schema_body, source, migration_body in _pairs()
        if schema_body != migration_body and name not in INTENTIONAL_DIVERGENCE
    ]

    assert not drifted, (
        "`schema.sql` ilə miqrasiya arasında fərq: "
        + ", ".join(f"{name} (sonuncu: {source})" for name, source in drifted)
        + ". Bazis sxem son versiyaya gətirilməli, VƏ YA fərq "
        "`INTENTIONAL_DIVERGENCE`-ə səbəbi ilə yazılmalıdır."
    )


def test_the_anti_fraud_guard_carries_the_priority_rule() -> None:
    """Ən kritik hal AYRICA kilidlənir — ümumi qapı ondan asılı qalmasın.

    Yuxarıdakı test bütün obyektlərə baxır və gələcəkdə kimsə pozuntunu
    `INTENTIONAL_DIVERGENCE`-ə yazaraq susdura bilər. Bu qayda isə
    struktur zəmanətdir (CLAUDE.md §5): prioritet-əsaslı qadağa hər iki
    tərifdə OLMALIDIR — istisnası yoxdur.
    """
    schema = _SCHEMA.read_text(encoding="utf-8", errors="replace")
    match = _FUNCTION.search(schema)
    bodies = {m.group(1).lower(): m.group(0) for m in _FUNCTION.finditer(schema)}
    assert match is not None, "schema.sql-də heç bir plpgsql funksiyası tapılmadı"

    guard = bodies.get("enforce_anti_fraud_segregation")
    assert guard is not None, "`enforce_anti_fraud_segregation()` schema.sql-dən itib"
    assert "v_priority" in guard, (
        "anti-fraud qapısı prioritet qaydasını daşımır — custom 'satıcı-pilləli' "
        "rol DB səviyyəsində anti-fraud flag-i ala bilər (bax modul başlığı)"
    )
    assert ">= 4" in guard, "prioritet həddi 048-dəki dəyərlə (4) uyğun gəlmir"


def test_the_divergence_registry_is_not_stale() -> None:
    """Siyahıdakı ad artıq fərqli deyilsə, sətir SİLİNMƏLİDİR.

    Köhnəlmiş istisna qapının ən sakit uğursuzluq formasıdır: ad orada qalır,
    fərq isə real deyil — yəni növbəti həqiqi fərq həmin adla gəlsə, sükutla
    keçər.
    """
    actually_different = {
        name
        for name, schema_body, _source, migration_body in _pairs()
        if schema_body != migration_body
    }
    stale = sorted(set(INTENTIONAL_DIVERGENCE) - actually_different)
    assert not stale, f"`INTENTIONAL_DIVERGENCE`-dəki bu adlar artıq fərqlənmir: {stale}"


def test_no_migration_only_function_or_trigger_is_left_unexplained() -> None:
    """D4: `_pairs()`-in görmədiyi boşluq — obyekt YALNIZ miqrasiyada var.

    `test_shared_objects_are_defined_identically` YALNIZ hər İKİ tərəfdə DƏ
    mövcud olan adları müqayisə edir. Miqrasiyada yaranıb `schema.sql`-ə HEÇ
    VAXT köçürülməyən `CREATE OR REPLACE FUNCTION`/`CREATE TRIGGER` bu
    yoxlamaya HEÇ VAXT DÜŞMÜR — məhz bu boşluqda `enforce_position_flag_
    hierarchy()` (046) illərlə görünmədi: `schema.sql`-dən quraşdırılan
    bazada Strict Hierarchy Guard `position_permissions` üzərində YOX idi.
    """
    unexplained = sorted(_migration_only_function_and_trigger_names() - set(MISSING_FROM_SCHEMA))
    assert not unexplained, (
        "Bu FUNCTION/TRIGGER YALNIZ miqrasiyada var, `schema.sql`-də YOXDUR: "
        + ", ".join(unexplained)
        + ". Ya `schema.sql`-ə köçürün (bax `enforce_position_flag_hierarchy`, "
        "046 → §18, D4 audit), ya da `MISSING_FROM_SCHEMA`-ya SƏBƏBİ ilə yazın."
    )


def test_the_missing_from_schema_registry_is_not_stale() -> None:
    """`INTENTIONAL_DIVERGENCE`-in bacısı — köhnəlmiş istisna sükutla keçməsin."""
    still_missing = _migration_only_function_and_trigger_names()
    stale = sorted(set(MISSING_FROM_SCHEMA) - still_missing)
    assert not stale, f"`MISSING_FROM_SCHEMA`-dəki bu adlar artıq köçürülüb: {stale}"
