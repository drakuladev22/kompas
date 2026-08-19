# DÖVRƏ 1 — domain hesabatı
[DOM-01] LOW ports.py:1512 AuthSessionRepository.list_recent_for_user(limit=10) — şərhsiz sabit; PANEL_LIMIT presedentinə bənzəyir, izah əskikdir.
[DOM-02] LOW fine_management.py:83 DUPLICATE_SUBMISSION_WINDOW_SECONDS=10 — kodda əsaslandırılıb, CLAUDE.md §5 BAĞLI cədvəlinə yazılmayıb. ARCHITECT qərarı lazımdır.
[DOM-03] MED (pre-existing) PENDING_RECONCILIATION statusunu HƏLL EDƏN axın yoxdur — status əbədi asılı qalır. Yalnız bildiriş enum-unda görünür (controllers/notifications.py:70).
SUAL -> infra: CLAUDE.md §8 flag kataloqu 54 → 55 (can_revoke_sessions, 072) yenilənməyib.
SUAL -> qa: SessionManagementUseCase, resolve_work_date (gecə növbəsi), MonthlyFineReviewUseCase üçün test örtüyü yoxlanmalıdır.
TƏMİZ: SessionManagementUseCase, resolve_work_date/D10, Fine.idempotency_key/D7, FineReviewBatch, employee.py:246 (SEC-001 bypass BAĞLANIB), telegram_config.save(is_active=None), Feature Toggle retroaktivliyi, hadisə yayımı/rollback, Clock portu.
AÇIQ QALDI: leave_verification._event_bus composition.py-da HƏQİQƏTƏN bağlanıbmı — domain yoxlamadı (ui sahəsi).
