KompasOS-da indiyə qədər yazılan HƏR ŞEYİ (əsas sistem, Face Control,
12-funksiyalı genişlənmə, HR-Ops genişlənməsi — 4 blok, 30+ faza) KOD
BAXIMINDAN son bir dəfə yoxlayıram. Məqsəd İKİ FƏRQLİ risk növünü tapmaq:
(1) ümumi boşluqlar (natamam/yazılmamış hissələr), (2) KOD TOQQUŞMASI —
müxtəlif fazalarda/agentlər tərəfindən yazılan hissələrin bir-biri ilə
ÜST-ÜSTƏ DÜŞMƏSİ və buna görə EXCEPTION QAYTARMASI (dublikat cədvəl/
miqrasiya, təkrarlanan sinif/funksiya adı, dairəvi import, uzlaşmayan
funksiya-imzası və s.).

===============================================================================
QIRMIZI XƏTT
===============================================================================
Bu, audit-dir — tapılanları düzəltmək lazım gələcək, amma HEÇ BİR işləyən
funksionallıq SİLİNMİR. İki eyni-məqsədli parça tapılsa (məs. eyni cədvəl
iki fərqli miqrasiyada), İKİSİNİ DƏ silib sıfırdan yazmaq ƏVƏZİNƏ, hansının
DAHA ƏVVƏL yazıldığını/daha çox yerdə istifadə olunduğunu tap, O QALSIN,
təkrarı ORA İSTİNAD EDƏCƏK şəkildə YENİLƏ (silmə, düzəlt).

===============================================================================
FAZA 0A — TOKEN-QƏNAƏT AYARLARI
===============================================================================
.claude/settings.json-da (mövcud deyilsə yarat, mövcuddursa TƏKRAR ƏLAVƏ
ETMƏ) bu qadağaların olduğunu təsdiqlə:
{
  "permissions": {
    "deny": [
      "Read(.venv/**)", "Read(venv/**)", "Read(node_modules/**)",
      "Read(dist/**)", "Read(build/**)", "Read(__pycache__/**)",
      "Read(*.pyc)", "Read(.git/**)"
    ]
  }
}

===============================================================================
FAZA 0B — 3 SUBAGENT YARAT (YENİ TİP — İNTEQRASİYA AUDİTİ)
===============================================================================

--- 1. integration-conflict-auditor (AUDİTOR — yalnız tapır) ---
---
name: integration-conflict-auditor
description: Kod bazasında dublikat cədvəl/miqrasiya, təkrarlanan sinif/
  funksiya adı, dairəvi import, uzlaşmayan funksiya-imzası kimi TOQQUŞMA
  nöqtələrini tapır. YALNIZ tapır, düzəltmir.
tools: Read, Grep, Glob
permissionMode: plan
model: sonnet
---
Sən Senior Code Integration Auditor-san. Bütün src/ (VƏ bütün migration/
schema fayllarını) tara, bunları axtar:
1. DUBLİKAT CƏDVƏL/SÜTUN TƏRİFİ — eyni cədvəl adı iki fərqli miqrasiya
   faylında tərif olunubmu (xüsusilə `work_modes`, `system_limits`,
   `feature_toggles`, `exceptions`, `face_verification_log` kimi bir neçə
   promptda toxunulan cədvəllərə diqqət et).
2. TƏKRARLANAN SİNİF/FUNKSİYA ADI — eyni ad, fərqli fayllarda, fərqli
   məzmunla (Python-da bu, import-zamanı səssizcə bir-birini üstələyə
   bilər, XƏTA vermədən — buna görə xüsusi diqqətlə axtar).
3. DAİRƏVİ IMPORT — A modulu B-ni, B modulu A-nı import edir.
4. UZLAŞMAYAN FUNKSİYA-İMZASI — bir use case başqa bir mövcud funksiyanı
   çağırır, amma parametr sayı/tipi uyğun gəlmir.
5. EYNİ CƏDVƏLƏ YAZAN, BİR-BİRİNDƏN XƏBƏRSİZ İKİ USE CASE — məs. həm
   Export Manual Corrections, həm Export Calculation eyni sətri paralel
   dəyişdirə bilərmi (race condition)?
Hər tapıntını: [Fayl A, sətir] | [Fayl B, sətir] | [Toqquşmanın növü] |
[Ehtimal olunan nəticə (hansı exception)] formatında göstər.
AXTARIŞ MƏHDUDİYYƏTİ: Əvvəlcə `grep -rn "class X\|def X\|CREATE TABLE X"`
tipli axtarışlarla adları tap, YALNIZ şübhəli uyğunluq tapılanda tam faylı
oxu. SƏRT TAVAN: 10000 tokendan çox işlətməyə başlasan, DAYAN, qismən
hesabat ver.

--- 2. runtime-verification-engineer (REAL İŞƏ-SALMA) ---
---
name: runtime-verification-engineer
description: Kodu FAKTİKİ işə salıb (pytest + tətbiqin özü), real
  exception-ləri tutur — statik analizin görə bilmədiyi problemləri tapır.
tools: Read, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən QA/Release Engineer-sən. Bunları ardıcıl icra et:
1. `pytest -v` tam paketini işə sal, HƏR uğursuz testi tam traceback-i ilə
   göstər (yalnız "keçdi/keçmədi" demə, XƏTANI göstər).
2. Tətbiqi başlatmağa cəhd et (`python main.py` və ya müvafiq giriş
   nöqtəsi) — istənilən import-error/startup-exception-i tam tutub göstər.
3. Əgər DB miqrasiyaları varsa, hamısını sıfırdan (təmiz test bazasında)
   tətbiq etməyə cəhd et — hansısa miqrasiya "table already exists" kimi
   xəta versə, bu, dublikat-tərif siqnalıdır, dəqiq hansı fayl olduğunu
   göstər.
Bu FAZA HEÇ NƏ DÜZƏLTMİR — yalnız REAL, konkret xəta mesajlarını toplayır.

--- 3. integration-conflict-resolver (FIXER) ---
---
name: integration-conflict-resolver
description: integration-conflict-auditor və runtime-verification-
  engineer-in tapdıqlarını düzəldir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Platform Engineer-sən. Tapılan HƏR toqquşmanı QIRMIZI XƏTT
qaydasına görə düzəlt: hansı versiya "əsas/doğru" olmalıdırsa onu saxla,
təkrarı ona istinad edəcək şəkildə yenilə. Hər düzəlişdən sonra dərhal
test et (ilgili pytest-i işə sal) ki, düzəliş yeni problem yaratmasın.

`/agents` ilə 3-ünün də qeydiyyatdan keçdiyini yoxla. "3 agent hazır" de,
FAZA 1-ə keç.

===============================================================================
FAZA 1 — STATİK TOQQUŞMA AUDİTİ — AGENT: integration-conflict-auditor
===============================================================================
Yuxarıdakı 5 toqquşma-növünü tam kod bazasında axtar. Nəticəni cədvəl kimi
göstər. **DAYAN, cədvəli göstər, təsdiq gözlə.**

===============================================================================
FAZA 2 — REAL İŞƏ-SALMA YOXLAMASI — AGENT: runtime-verification-engineer
===============================================================================
pytest + tətbiq-başlatma + miqrasiya-sıfırdan-tətbiq sınaqlarını işə sal.
Bütün real exception/traceback-ləri tam mətnlə göstər. **DAYAN, nəticəni
göstər, təsdiq gözlə.**

===============================================================================
FAZA 3 — DÜZƏLİŞ (PRİORİTETLƏŞDİRİLMİŞ) — AGENT: integration-conflict-resolver
===============================================================================
Faza 1 və 2-də tapılan HƏR problemi bu sıra ilə düzəlt (soruşmadan davam
et, hər düzəlişdən sonra qısa "[X] düzəldildi, test keçdi" yaz):
1. KRİTİK — tətbiqi başlatmayan/DB miqrasiyasını sındıran xətalar
2. ORTA — testləri uğursuz edən, amma tətbiqi bütövlükdə sındırmayan
3. KİÇİK — statik analizdə tapılan, hələ real xətaya çevrilməmiş riskli
   pattern-lər (məs. gələcəkdə toqquşa biləcək, indi hələ toqquşmayan)

**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 4 — TƏKRAR YOXLAMA (TƏMİZ ÇIXANA QƏDƏR)
===============================================================================
Faza 3 bitdikdən sonra, Faza 1 VƏ Faza 2-ni YENİDƏN işə sal. Hələ problem
varsa, Faza 3-ə qayıt, təkrarla. YALNIZ hər ikisi tam təmiz çıxanda dayandır.

===============================================================================
FAZA 5 — YEKUN HESABAT
===============================================================================
1. `git diff --stat` — nə qədər kod dəyişdirildiyini göstər.
2. Tam `pytest` nəticəsi (say + keçmə faizi).
3. Tətbiqin uğurla başladığını təsdiqlə.
4. Git-də "integration-audit-clean-v1" tag-i ilə commit et.
5. Yekun cədvəl: tapılan HƏR toqquşma/xəta | səbəbi | necə düzəldildi.
6. Aydın YEKUN cümlə: "Kod bazası toqquşmasızdır, real işə-salma təmizdir"
   VƏ YA hələ nəyin qaldığını dəqiq de.

QAYDA: Hər fazadan sonra DAYAN, mən "davam et" deməyincə növbətiyə keçmə.
