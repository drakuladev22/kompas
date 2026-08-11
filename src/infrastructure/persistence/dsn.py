"""DSN-in xarici alətlərə (`pg_dump`, `pg_restore`) təhlükəsiz ötürülməsi.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ ƏMR SƏTRİNDƏ OLMUR
──────────────────────────────────────────────────────────────────────────────
`postgres://user:PAROL@host/db` sətrini `--dbname` arqumenti kimi vermək ən
qısa yoldur, lakin əmr sətri ƏMƏLİYYAT SİSTEMİ SƏVİYYƏSİNDƏ AÇIQDIR: eyni
maşındakı istənilən proses onu `ps`/Task Manager/Process Explorer ilə oxuya
bilər. Şəbəkə şifrələməsi burada kömək etmir — sızma prosesin öz sətrindədir.

PostgreSQL alətləri şifrəni `PGPASSWORD` mühit dəyişənindən oxumağı dəstəkləyir;
mühit dəyişəni isə yalnız prosesin özünə və eyni istifadəçi altındakı ana
prosesə görünür. Ona görə DSN İKİYƏ bölünür: şifrəsiz hissə əmr sətrinə,
şifrə isə `env=` ilə ötürülür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL
──────────────────────────────────────────────────────────────────────────────
Eyni qayda İKİ yerdə lazımdır — gecəlik ehtiyat nüsxə (`backup/service.py`) və
baza keçidi (`persistence/migration.py`). Qayda hər iki faylda təkrar
yazılsaydı, biri düzələndə digəri sükutla köhnə (şifrəni açıq verən) qalardı;
məhz bu baş vermişdi. Funksiyalar burada BİR dəfə təyin olunur, köhnə adlar
isə öz yerlərində nazik örtük kimi saxlanılır ki, mövcud çağırışlar qırılmasın.
"""

from __future__ import annotations

from urllib.parse import urlparse


def password_env(dsn: str) -> dict[str, str]:
    """DSN-dəki şifrəni `PGPASSWORD` mühit dəyişəninə köçürür.

    Şifrə yoxdursa boş lüğət qaytarır — `env` birləşməsi belə halda cari
    mühiti olduğu kimi saxlayır (`PGPASSWORD`-u boş dəyərlə örtmür, çünki boş
    şifrə "şifrə yoxdur"dan FƏRQLİ bir cəhddir).
    """
    password = urlparse(dsn).password
    return {"PGPASSWORD": password} if password else {}


def dsn_without_password(dsn: str) -> str:
    """Şifrəsiz DSN — əmr sətrinə yalnız bu düşür.

    Şifrə yoxdursa sətir OLDUĞU KİMİ qaytarılır: `urlparse` + `geturl()`
    dövrəsi `postgres:///db` kimi qeyri-standart formaları normallaşdırıb
    dəyişdirə bilər, biz isə burada yalnız BİR şeyi dəyişmək istəyirik.
    """
    parsed = urlparse(dsn)
    if not parsed.password:
        return dsn
    netloc = parsed.netloc.replace(f":{parsed.password}@", "@", 1)
    return parsed._replace(netloc=netloc).geturl()


__all__ = ["dsn_without_password", "password_env"]
