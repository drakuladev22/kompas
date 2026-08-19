# SECURITY-AUDIT: YAYIMA ÇIXMAZDAN ƏVVƏL TAM TƏHLÜKƏSİZLİK YOXLAMASI

KompasOS-u müştəriyə təhvil verməzdən əvvəl tam təhlükəsizlik auditi
istəyirəm. Aşağıdakı 21 başlığın HƏR BİRİ üçün kod bazasını tara və mənə
TƏK BİR hesabat ver.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Bu addımda **HEÇ BİR FAYLI DƏYİŞMƏ** — yalnız tap və raporla. Düzəliş
sonrakı addımdır, mən qərar verəcəyəm.

===============================================================================
KONTEKST — BU, MASAÜSTÜ TƏTBİQDİR
===============================================================================
KompasOS native Windows masaüstü tətbiqidir (PySide6/Qt + `.exe`), veb
tətbiq DEYİL. Backend: Supabase (PostgreSQL + RLS). Ona görə:
- Brauzer-spesifik məsələlər (CORS, HTTP başlıqları, cookie-lər) UYĞUN
  DEYİL — onları axtarma
- Əvəzinə: `.exe` daxilində sirlər, lokal fayl təhlükəsizliyi, Qt-render
  inyeksiyası, Supabase RLS kimi məsələlər KRİTİKDİR

===============================================================================
FAZA 0 — AGENT (VARSA TƏKRAR YARATMA)
===============================================================================
--- security-audit-engineer ---
---
name: security-audit-engineer
description: Yayım-öncəsi tam təhlükəsizlik auditi. YALNIZ tapır və
  raporlayır, DÜZƏLTMİR.
tools: Read, Grep, Glob, Bash
permissionMode: plan
model: opus
---
Sən Senior Application Security Engineer-sən. Masaüstü tətbiq + Supabase
arxitekturası üzrə audit aparırsan. Əmin olmadığın yerdə "əmin deyiləm"
yaz — TƏXMİN ETMƏ. HEÇ NƏ DƏYİŞMƏ. AXTARIŞ MƏHDUDİYYƏTİ: src/,
migrations/, .spec, installer, scripts/ qovluqlarında işlə; .venv/dist/
build/node_modules-a girmə. Əvvəlcə `grep -l` ilə şübhəli faylları tap,
YALNIZ sonra tam oxu.

`/agents` ilə təsdiqlə, FAZA 1-ə keç.

===============================================================================
YOXLANILACAQ 21 BAŞLIQ
===============================================================================

**A. SİRLƏR VƏ KİMLİK MƏLUMATLARI**
1. `.exe`-yə paketlənən kodda/resurslarda duran API açarı, token, parol,
   şifrələmə açarı (hardcode edilmiş). **Xüsusi diqqət:** Supabase
   `service_role` açarı HEÇ VAXT `.exe`-də olmamalıdır.
2. Git tarixçəsinə düşmüş `.env`, config, açar faylı (`git log` ilə
   yoxla — indi silinsə də tarixçədə qala bilər).
3. `kompasos.config` faylının şifrələnməsi: açar necə əldə olunur, kim
   deşifrə edə bilər?

**B. SERVER-TƏRƏFİ QORUNMA (ƏN KRİTİK BÖLMƏ)**
4. Supabase RLS siyasətləri: hansı cədvəllərdə RLS AKTİV DEYİL? Anonim/
   adi istifadəçi hansı cədvəlləri oxuya/yaza bilər?
5. **Vendor cədvəlləri** (`tenants`, `vendor_accounts`, ödəniş
   məlumatları) — adi tenant istifadəçisi bunları görə bilirmi?
6. Yetki yoxlaması YALNIZ UI-da edilən yerlər — "GÖRMƏK=SƏLAHİYYƏT"
   prinsipi UI-dadır, amma arxada (use case/DB) da yoxlanılırmı? Kimsə
   birbaşa API çağırsa nə olar?
7. Admin/Root əməliyyatları (tenant deaktiv etmə, sistem limitləri
   dəyişmə, icazə verilməsi) serverdə rol-yoxlamasından keçirmi?
8. Hardlock qaydaları (anti-fraud flag-ləri, `can_manage_permissions`)
   DB-səviyyəsində (trigger/constraint) tətbiq olunubmu, yoxsa yalnız
   Python kodunda?

**C. GİRİŞ VƏ SESSİYA**
9. Login və şifrə-sıfırlama uclarında sürət-limiti (rate limit) varmı?
   PIN üçün lockout var — admin login üçün?
10. Şifrələr necə saxlanılır: argon2 istifadə olunurmu, parametrləri
    (memory, time cost) yetərlidirmi? Düz mətn/zəif hash varmı?
11. Lokal sessiya tokeni harada, necə saxlanılır? Şifrələnibmi? Eyni
    PC-də başqa istifadəçi oxuya bilərmi?
12. TOTP/2FA secret-ləri şifrələnmiş saxlanılırmı?

**D. GİRDİ VƏ İNYEKSİYA**
13. String birləşdirmə/f-string ilə qurulan SQL sorğuları (parametrized
    olmayan) — SQL injection riski.
14. **Qt-render inyeksiyası:** istifadəçi məzmunu (chat mesajları, işçi
    adları, cərimə səbəbləri) `QLabel`/`QTextEdit`/`QTextBrowser`-də
    zəngin-mətn (rich text/HTML) kimi render olunurmu? Escape edilirmi?
15. Yalnız client-də doğrulanan, serverdə doğrulanmayan girdilər —
    xüsusilə: vaxt-möhürləri, cərimə məbləği, icazə müddəti.
16. Fayl yükləmədə (profil şəkli, cərimə sübutu, sənəd, üz-enrollment)
    tip və ölçü limiti REAL tətbiq olunurmu (yalnız UI-da yoxlanılıb
    keçilə bilərmi)?

**E. ŞƏBƏKƏ VƏ İNTEQRASİYA**
17. Supabase/xarici sorğular yalnız HTTPS ilə gedirmi? HTTP-yə
    düşmə/sertifikat yoxlamasını söndürmə (`verify=False`) varmı?
18. Telegram bot: webhook istifadə olunursa, gələn sorğunun imzası/
    mənbəyi doğrulanırmı? Polling-dirsə, token necə qorunur?

**F. MƏLUMAT VƏ GİZLİLİK**
19. Loglara yazılan həssas məlumat: token, parol, PII, **üz-embedding**,
    tam Supabase açarı. Xəta mesajlarında iç detal sızmasıvarmı?
    (**Qeyd:** Root-a göstərilən diaqnostika ekranında detallı xəta
    QƏSDƏNDİR — bu, problem sayılmır; adi işçiyə göstərilənləri yoxla.)
20. Hesab deaktiv/silmə: `face_embedding` HƏQİQƏTƏN silinirmi (biometrik
    məlumat üçün hüquqi tələb)? Digər PII arxada qalırmı?
21. Backup/restore mexanizmi real işləyirmi? Backup faylları
    şifrələnibmi, kim çıxış edə bilər?

**G. ƏLAVƏ**
22. Asılılıqlar: bilinən zəiflikli və ya versiyası sabitlənməmiş paketlər
    (`requirements.txt`-də `>=` və ya versiyasız yazılanlar).
23. Supabase kvota/limit aşımı halında xəbərdarlıq mexanizmi varmı
    (xidmət səssizcə dayanmasın)?
24. Yetkisiz çıxışla SINANMAMIŞ uclar — hansı kritik əməliyyatlar üçün
    "icazəsiz istifadəçi bunu edə bilmir" testi YOXDUR?

===============================================================================
HESABAT FORMATI (HƏR TAPINTI ÜÇÜN)
===============================================================================
- **Başlıq nömrəsi**
- **fayl:sətir**
- **Nə səhvdir** (bir cümlə)
- **Risk:** kritik / yüksək / orta
- **Təklif olunan düzəliş** (bir cümlə)

**Hesabatın sonunda:**
1. Hansı başlıqların TƏMİZ çıxdığını sadala
2. Hansı başlıqlarda "əmin deyiləm" olduğunu VƏ NİYƏ (məs. "bu hissə
   runtime-da yoxlanmalıdır, statik analizlə görünmür") sadala
3. Risk səviyyəsinə görə ÜMUMİ xülasə: neçə kritik, neçə yüksək, neçə orta

===============================================================================
QAYDA
===============================================================================
- HEÇ NƏ DƏYİŞMƏ, yalnız raporla.
- Əmin olmadığın yerdə "əmin deyiləm" yaz, TƏXMİN ETMƏ.
- Hesabatı bitirdikdən sonra DAYAN, mən hansı maddələri düzəltmək
  istədiyimi seçəcəm.
