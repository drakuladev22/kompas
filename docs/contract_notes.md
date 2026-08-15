# Müqavilə və Hüquqi Qeydlər

Bu sənəd kod deyil — `kompasos.md`-nin **hüquqi/müqavilə tələblərini** bir
yerə yığır. Hər iki bənd spesifikasiyada məcburi kimi yazılıb, lakin onların
yerinə yetirilməsi proqramlaşdırma ilə deyil, sənədləşmə ilə olur.

---

## 1. Şəffaflıq maddəsi — uzaqdan idarəetmə modulu

**Mənbə:** bölmə 8 — *"ŞƏFFAFLIQ MADDƏSİ: Bu modulun mövcudluğu satış
müqaviləsində açıq şəkildə qeyd olunmalıdır."*

Söhbət Developer (Master) Panelindən gedir: hazırlayıcı tərəf tenant-ı uzaqdan
deaktiv edə, lisenziyanı uzada, məcburi yenilənmə tətbiq edə və aqreqasiya
edilmiş telemetriya görə bilir. Müştəri bunu **müqavilə imzalayarkən**
bilməlidir — sonradan aşkar edilməsi etibar məsələsidir.

**ADLANDIRMA QEYDİ (vacib, çünki müqavilə mətninə də təsir edir):** buradakı
"Master" sözü tenant-daxili rol iyerarxiyasının bir pilləsi DEYİL. Müştərinin
`Root` istifadəçisi öz sistemində mütləq ən yuxarıdır və onun ÜSTÜNDƏ heç bir
"Master Root" hesabı yoxdur. Hazırlayıcı tərəfin panelı yalnız **abunəni**
(aktiv/deaktiv, ödəniş, versiya, aqreqat telemetriya) idarə edir; tenant-ın
daxilində — işçi, rol, icazə, cərimə, hesabat — heç bir səlahiyyəti yoxdur.
Bu iki sistem qəsdən ayrıdır və müqavilə mətni də onları qarışdırmamalıdır.

### Müqaviləyə salınacaq mətn (təklif)

> **Uzaqdan idarəetmə və lisenziya nəzarəti.** Təchizatçı KompasOS
> proqram təminatının lisenziya vəziyyətini uzaqdan idarə edən texniki
> vasitəyə malikdir. Bu vasitə ilə Təchizatçı: (a) lisenziyanın müddətini
> uzada, (b) ödəniş öhdəliyi yerinə yetirilmədikdə quraşdırmanı müvəqqəti
> deaktiv edə, (c) proqram təminatının yeni versiyasının tətbiqini tələb
> edə, (d) sistemin sağlamlığına dair aqreqasiya edilmiş texniki
> göstəriciləri (aktiv istifadəçi sayı, server sayı, sinxronizasiya
> vəziyyəti, anonimləşdirilmiş xəta hesabatları) əldə edə bilər.
>
> Deaktivləşdirmə **məlumat itkisinə səbəb olmur** — Müştərinin məlumatları
> tam qorunur və ödəniş bərpa edildikdə giriş dərhal açılır.
>
> Təchizatçı Müştərinin işçilərinə aid **şəxsi məlumatlara (PII) uzaqdan
> çıxış əldə etmir**. Yeganə istisna — Müştərinin bütün inzibatçı hesabları
> itirildikdə, Müştərinin qeydiyyatdakı rəsmi əlaqə vasitəsi ilə kimliyi
> təsdiqləndikdən sonra icra olunan və tam audit-lənən birdəfəlik "Təcili
> Giriş Bərpası" prosedurudur.

### Niyə son abzas vacibdir

Bölmə 8 açıq deyir: *"heç bir halda işçi PII-sinə uzaqdan çıxış YOXDUR"*.
Lakin bölmə 2-dəki Emergency Access Recovery proseduru istisnadır. Müqavilədə
yalnız birincisi yazılsaydı, prosedurun özü müqaviləyə zidd görünərdi.

---

## 2. Əmək və şəxsi məlumat qanunvericiliyi üzrə məsləhət

**Mənbə:** bölmə 6 — *"UYĞUNLUQ QEYDİ: Kamera-əlaqəli izləmə və cərimə
sistemi tətbiqə düşməzdən əvvəl yerli Əmək Məcəlləsi və şəxsi məlumatların
qorunması qanunvericiliyi üzrə hüquqi məsləhət alınmalıdır."*

Bu, **quraşdırmadan ƏVVƏL** bağlanmalı bir addımdır, sonrakı düzəliş deyil.

### Hüquqşünasa verilməli konkret suallar

| Mövzu | Sual |
|---|---|
| Cərimə mexanizmi | Cərimələr əsas maaşdan deyil, **premiyadan** tutulur (bölmə 6, FAYL 2). Bu forma Əmək Məcəlləsinə uyğundurmu və əmək müqaviləsində necə əks olunmalıdır? |
| Kamera müşahidəsi | İşçilər video-müşahidə və onun əmək intizamı qərarlarında istifadəsi barədə hansı formada məlumatlandırılmalıdır? |
| Vaxt uçotu | PIN + kamera təsdiqli giriş/çıxış qeydləri rəsmi tabel kimi qəbul edilirmi? |
| Məlumat saxlama | `audit_logs` və cərimə qeydləri nə qədər saxlanılmalıdır (minimum/maksimum)? |
| İşçi hüququ | 72 saatlıq etiraz pəncərəsi (bölmə 4) qanunvericilikdəki şikayət müddəti ilə uyğundurmu? |
| Profil şəkli | İşçi şəkillərinin saxlanması və Kamera Operatoruna göstərilməsi üçün ayrıca razılıq tələb olunurmu? |

### Sistemin bu suallara hazır olan tərəfi

Aşağıdakılar artıq kodda təmin olunub və hüquqşünasa təqdim edilə bilər:

- Heç bir cərimə **avtomatik tutulmur**: 72 saatlıq etiraz pəncərəsi
  bağlanmayana qədər export-a düşmür (bölmə 6 LOCK mexanizmi).
- Ləğv edilmiş cərimə **silinmir** — `REVERSED` statusu əlavə olunur, orijinal
  qeyd toxunulmaz qalır (bölmə 4).
- Hər manual müdaxilə (vaxt override, cərimə, icazə dəyişikliyi) `audit_logs`-da
  icraçı ID-si və məcburi səbəb mətni ilə saxlanılır.
- Video görüntü **saxlanılmır və proqrama daxil edilmir** — KompasOS iVMS ilə
  heç bir inteqrasiyaya malik deyil (bölmə 4).
