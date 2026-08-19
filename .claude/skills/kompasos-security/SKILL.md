---
name: kompasos-security
description: KompasOS təhlükəsizlik zəmanətləri — RLS, vendor izolyasiyası, sirr idarəetməsi, SQL parametrizasiyası, biometrik silinmə, server vaxtı. Təhlükəsizliyə toxunan hər dəyişiklikdən əvvəl və sonra oxu.
---

# KompasOS — Təhlükəsizlik Zəmanətləri

## Əsas prinsip

**Təhlükəsizlik CLIENT-də deyil, SERVERDƏ olur.** UI-da düyməni gizlətmək
qorunma DEYİL — o, yalnız erqonomikadır. Həqiqi qapı Supabase RLS + server
tərəfi yoxlamadır. Ekranı yan keçən skript də eyni qaydaya tabe olmalıdır;
ona görə yoxlama İKİ yerdə olur: use case-də VƏ repository/DB-də.

## 1. RLS — hər cədvəldə

* Hər tenant cədvəlində RLS aktiv olmalıdır.
* Repository `self._tenant` ilə AÇIQ `tenant_id` şərti qoyur — bu, RLS-ə
  ƏLAVƏ ikinci qatdır, onun əvəzi deyil. Səbəb: bir qat sükutla söndürülsə
  digəri hələ tutur.
* Vendor cədvəlləri (`tenants`, `vendor_accounts`, ödəniş cədvəlləri) adi
  tenant istifadəçisindən RLS ilə qorunur. Tenant istifadəçisi başqa
  tenant-ın sətrini GÖRMƏMƏLİDİR.

**Yoxlama sualı:** «Bu cədvəldə RLS yoxdursa — qəsdəndirmi, yoxsa
unudulub?» Cavab «unudulub»dursa bu, CRITICAL tapıntıdır.

## 2. Sirrlər

* `service_role` açarı HEÇ VAXT `.exe`-yə paketlənmir.
* `KOMPASOS_FERNET_KEY`, `KOMPASOS_HASH_PEPPER` istehsalatda boş ola bilməz
  (`--strict` işə düşmür).
* Loglara token / parol / PII / **üz-embedding** YAZILMIR.
* Şübhəli sızmış açar dərhal ROTASİYA edilir və işarələnir.

## 3. SQL

100% parametrizasiya (`%s`). String birləşdirmə YOXDUR. Dinamik `WHERE`
şərtləri yalnız SABİT sətir siyahısından qurulur və
`# noqa: S608 — şərtlər sabit siyahıdandır` şərhi ilə işarələnir.

Prompt injection də bura aiddir: xarici mətn (Telegram mesajı, dəstək
müraciəti, fayl adı) heç vaxt təlimat kimi icra olunmur.

## 4. Biometrik məlumat

İşçi deaktiv olanda `face_embedding` HƏQİQƏTƏN silinir — bu, hüquqi
tələbdir, «soft delete» kifayət etmir.

Sxem bunu maşınla təsbit edir:
`CHECK ((status = 'PURGED') = (face_embedding IS NULL))` — yəni status ilə
məlumatın mövcudluğu bir-birinə bağlıdır və yalan danışa bilməz.

**MƏNBƏ:** `src/domain/value_objects/face_recognition.py`,
`src/application/use_cases/user_management.py` (`_purge_face_embedding`).

## 5. Vaxt bütövlüyü (TIME-1)

Kritik vaxt-möhürləri client-dən QƏBUL EDİLMİR. `created_at` (cərimə,
etiraz, icazə, davamiyyət) və `fines.published_at` `BEFORE INSERT/UPDATE`
trigger-i ilə server vaxtına məcbur edilir.

`DEFAULT now()` TƏK BAŞINA KİFAYƏT ETMİR — sütunun adı `INSERT`-də açıq
çəkiləndə default yan keçilir, və repozitoriyaların bir qismi məhz belə
yazırdı. Ona görə trigger var.

**MƏNBƏ:** `migrations/062`, `src/infrastructure/timekeeping/server_time.py`.

## 6. Audit istisna udmur

`AuditTrail.record()` uğursuz olarsa BÜTÜN əməliyyat geri qaytarılır.
Məcburi olan bir şeyin sükutla buraxılması onu məcburi olmaqdan çıxarır.
`try/except: pass` ilə audit yazısını «xilas etmək» qadağandır.

## 7. Miqrasiyalar

Miqrasiya YALNIZ icraçı ilə tətbiq olunur:

```bash
.venv/Scripts/python.exe scripts/apply_migrations.py --dry-run
.venv/Scripts/python.exe scripts/apply_migrations.py
```

Faylı əl ilə SQL redaktorunda işlətmək QADAĞANDIR — `schema_migrations`
reyestrində iz qalmaz. DB-5 auditi 60 miqrasiyadan 11-inin heç vaxt tətbiq
olunmadığını, 32 cədvəlin isə mövcud olmadığını məhz bu boşluqda tapmışdı.

**SÜTUN yox, QAYDA dəyişirsə hər İKİ yer yenilənir:** miqrasiya
`schema.sql`-də artıq mövcud trigger/indeks/constraint-i yenidən yazırsa,
bazis sxemdəki nüsxə DƏ yenilənməlidir. `tests/unit/test_schema_migration_parity.py`
bunu maşınla yoxlayır.

## 8. Tapıntı formatı

Hər tapıntı: **severity + fayl:sətir + nə səhvdir + niyə əhəmiyyətlidir +
təklif olunan düzəliş**.

* **CRITICAL** — canlıya çıxmağa MANE olur (açıq sirr, itmiş auth yoxlaması,
  SQL injection, RLS-siz vendor cədvəli)
* **HIGH** — növbəti buraxılışdan əvvəl
* **MEDIUM / LOW** — sahəyə toxunanda

Təhlükəsizliyi «keyfiyyət yaxşı görünür» deyə ATLAMA. «Əmin deyiləm» demək
icazəlidir — TƏXMİN etmək qadağandır.
