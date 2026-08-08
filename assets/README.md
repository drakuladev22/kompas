# assets/

## `kompasos.ico` — MÜVƏQQƏTİ PLACEHOLDER

Bu fayl **avtomatik yaradılmış placeholder-dır** (Deep Navy fon + Amber "K",
bax dizayn sistemi, bölmə 9). Format düzgündür və build-i qırmır:

| Xüsusiyyət | Dəyər |
|---|---|
| Format | ICO, PNG-sıxılmış |
| Ölçülər | 16×16, 32×32, 48×48, 256×256 |
| Rənglər | `#0B1D3A` (Deep Navy) / `#F5A623` (Amber) |

**Faza 4-dən əvvəl müştərinin real loqosu ilə əvəz edilməlidir.** Spesifikasiya
bölmə 9 tələb edir:

- eyni loqo splash screen-də, pəncərə başlığında, Taskbar/Alt-Tab-da və `.exe`
  faylının özündə istifadə olunur;
- dörd ölçü (16/32/48/256) bulanıqlaşma olmadan hazırlanır;
- dark/light temada kontrast itməməsi üçün lazım gələrsə **iki variant**
  (`kompasos-light.ico`, `kompasos-dark.ico`) hazırlanır.

### Əvəzləmə

Yeni `.ico` faylını eyni adla bu qovluğa qoyun — `ci.yml`-dakı PyInstaller
addımı avtomatik onu götürür. Splash screen üçün əlavə olaraq yüksək
keyfiyyətli PNG (minimum 512×512, şəffaf fon) da lazımdır:
`assets/kompasos-splash.png`.

### Yenidən yaratmaq (placeholder)

`scripts/generate_placeholder_icon.ps1` faylına baxın.
