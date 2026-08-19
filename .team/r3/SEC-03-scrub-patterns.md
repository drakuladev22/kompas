# SEC-03 — crash_reporter.scrub() üçün nümunələr (security təyin etdi, infra tətbiq edəcək, DÖVRƏ 3)
1. URL-daxili kimlik (ƏN VACİB): `://[^/\s:@]+:([^@\s]+)@`  — DSN-lərin ümumi forması
2. libpq boşluqlu conninfo: `(?i)password=\S+`
3. Telegram bot token: `\b\d{6,10}:[A-Za-z0-9_-]{35}\b`
4. Google OAuth: `\bya29\.[0-9A-Za-z_-]+\b`, `\b1//[0-9A-Za-z_-]+\b`
5. Authorization/Bearer: `(?i)authorization:\s*\S+`, `(?i)\bBearer\s+[A-Za-z0-9\-_.]+\b`
6. Generic açar=dəyər toru: `(?i)\b(password|pwd|secret|token|api[_-]?key|client_secret)\s*[:=]\s*\S+`
7. Argon2id hash: `\$argon2id\$v=\d+\$[^\s]+`
Fernet açarı QƏSDƏN siyahıda YOX — heç bir kod yolu onu string-ə interpolasiya etmir.
