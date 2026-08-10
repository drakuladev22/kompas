# Mağaza Quraşdırması — Şəbəkə Tələbləri və Ehtiyat Cihaz

Mənbə: `kompasos.md` bölmə 5 (OFFLINE-FIRST & SYNC STRATEGY) — iki bənd bu
sənədi açıq şəkildə tələb edir:

> **Şəbəkə:** mağaza ↔ Supabase əlaqəsi üçün tələb olunan portlar/VPN tələbi
> sənədləşdirilir.
>
> **Failover:** hər mağazada minimum 1 ehtiyat cihaz müəyyən edilir ki, əsas
> PC sıradan çıxdıqda PIN handshake/Camera Dashboard tam dayanmasın.

Bu sənəd 21 filialın hər biri üçün quraşdırma zamanı doldurulur.

---

## 1. Şəbəkə tələbləri

### 1.1 Çıxış portları (mağaza PC → internet)

Bütün bağlantılar **çıxışa doğrudur** (outbound). Mağazaya daxil olan
(inbound) heç bir port açılmır — bu, qəsdəndir: kassa PC-si internetdən
əlçatan olmamalıdır.

| Hədəf | Port | Protokol | Nə üçün |
|---|---|---|---|
| `<ref>.supabase.co` | 443 | TCP/TLS | PostgREST, Storage, Realtime (WebSocket) |
| `aws-0-<region>.pooler.supabase.com` | 5432 | TCP/TLS | Birbaşa PostgreSQL (connection pooler) |
| NTP serveri (`pool.ntp.org` və ya daxili) | 123 | UDP | Saat sinxronizasiyası — bölmə 2 |
| SMTP relay (e-poçt fallback) | 587 | TCP/STARTTLS | Kritik bildirişlər — bölmə 7 |

**443 kifayət etmir.** Tətbiq `psycopg` ilə birbaşa PostgreSQL-ə də qoşulur
(offline buferin sinxronizasiyası və hesabat ixracı), ona görə 5432 ayrıca
açılmalıdır. Yalnız 443 açıq olan şəbəkədə proqram işə düşür, lakin
sinxronizasiya səssizcə `PENDING` vəziyyətində yığılır.

### 1.2 Port 123 (NTP) niyə məcburidir

Bölmə 2: saat fərqi 60 saniyəni keçdikdə `TIME_DRIFT_DETECTED` işə düşür və
**PIN handshake ilə manual override bloklanır**. UDP/123 bağlıdırsa saat
sürüşməsi düzəlmir və mağaza bir müddət sonra icazə axınını ümumiyyətlə
işlədə bilmir. Bu, "proqram işləmir" zənglərinin ən sakit səbəbidir.

### 1.3 VPN

VPN **məcburi deyil** — bütün bağlantılar TLS ilə şifrələnir və Supabase
tərəfdə RLS qüvvədədir. VPN yalnız iki halda tələb olunur:

1. **Özəl serverə keçid** (bölmə 2 Hybrid DB Switcher) — baza müştərinin öz
   serverindədirsə, mağaza ilə server arasında site-to-site VPN qurulur;
   5432 heç vaxt birbaşa internetə açılmır.
2. Müştərinin daxili təhlükəsizlik siyasəti bütün xarici trafiki VPN-dən
   keçirməyi tələb edirsə.

VPN işlədilirsə **split-tunnel tövsiyə olunur**: 1C serverləri adətən
daxili şəbəkədədir, Supabase isə xaricdə — tam tunel bu ikisindən birini
əlçatmaz edir.

### 1.4 Domen ağ siyahısı (proxy/firewall)

```
*.supabase.co
*.pooler.supabase.com
```

Ayrıca update serveri, CDN və ya domen **YOXDUR** (bölmə 7) — yenilənmə də
Supabase Storage-dakı `app-updates` bucket-indən gəlir, yəni yuxarıdakı iki
domendən başqa heç nə açılmır.

### 1.5 Filial üzrə doldurulan cədvəl

| Filial | Xarici IP | Provayder | 443 | 5432 | 123/UDP | 587 | VPN | Yoxlanma tarixi |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

---

## 2. Ehtiyat cihaz (failover)

### 2.1 Tələb

Hər mağazada **ən azı bir** ehtiyat cihaz müəyyən edilir. Məqsəd əsas kassa
PC-si sıradan çıxdıqda bu iki axının dayanmamasıdır:

- **PIN handshake** — işçi günə başlaya, icazə istəyə və qayıda bilməlidir.
  Dayanarsa gün "İcazəsiz Qayıb" kimi qeydə düşür (bölmə 4) və sonradan əl
  ilə düzəldilməli olur.
- **Camera Operator Dashboard** — təsdiq növbəsi dayanarsa 45 dəqiqəlik
  timeout işə düşür və hər sorğu HR_Admin/CEO-ya eskalasiya olunur.

### 2.2 Ehtiyat cihaz nə OLMALI deyil

Ayrıca alınmış, boş dayanan bir PC **tələb olunmur**. Ehtiyat kimi mağazada
onsuz da mövcud olan bir cihaz təyin edilir (menecer noutbuku, ikinci kassa
PC-si). Şərt sadədir: KompasOS quraşdırılıb, şəbəkə tələbləri ödənilir və
**hansı cihaz olduğu əvvəlcədən yazılıb** — nasazlıq anında "hansı PC-dən
girək?" sualının cavabı axtarılmamalıdır.

### 2.3 Keçid proseduru

1. Ehtiyat cihazda KompasOS açılır (quraşdırma əvvəlcədən edilib).
2. İşçilər PIN-i həmin cihazda daxil edir — **əlavə konfiqurasiya
   lazım deyil**, PIN tenant səviyyəsindədir, cihaza bağlı deyil.
3. Əsas PC-də qalan sinxronlaşmamış offline bufer İTMİR: cihaz bərpa
   olunduqda `sync_worker` onu adi qaydada göndərir (bölmə 5).
4. Kiosk rejimi işlədilirsə ehtiyat cihazda da watchdog ilə açılır
   (`--gui --kiosk`, bax `--watchdog`).

### 2.4 Filial üzrə doldurulan cədvəl

| Filial | Əsas cihaz | Ehtiyat cihaz | KompasOS quraşdırılıb? | Son sınaq |
|---|---|---|---|---|
| | | | | |

**Son sınaq** sütunu boş qalmamalıdır: sınanmamış ehtiyat cihaz ehtiyat
deyil, fərziyyədir. Rübdə bir dəfə ehtiyat cihazdan bir PIN handshake
edilməsi kifayətdir.
