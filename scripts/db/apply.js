#!/usr/bin/env node
/**
 * SQL faylını PostgreSQL/Supabase-ə tətbiq edir — `psql` OLMADAN.
 *
 * Nəyə lazımdır: `schema.sql` psql meta-əmrlərindən istifadə edir
 * (`\set`, `\if`, `:'kompasos_env'`). Bu skript onları emal edib SQL-i
 * node-postgres ilə icra edir, beləliklə PostgreSQL client quraşdırmadan da
 * sxem tətbiq oluna bilir.
 *
 * Quraşdırma (bir dəfə):
 *     cd scripts/db && npm install
 *
 * İstifadə:
 *     $env:SB_HOST     = 'aws-0-ap-southeast-1.pooler.supabase.com'
 *     $env:SB_REF      = '<project-ref>'
 *     $env:SB_PASSWORD = '<şifrə>'
 *     node scripts/db/apply.js database/schema.sql DEV
 *     node scripts/db/apply.js database/tests/test_guards.sql
 *
 * Alternativ (tam bağlantı sətri ilə):
 *     $env:DATABASE_URL = 'postgresql://user:pass@host:5432/postgres'
 *     node scripts/db/apply.js database/schema.sql DEV
 *
 * XƏBƏRDARLIQ: Supabase-in BİRBAŞA host-u (db.<ref>.supabase.co) yalnız
 * IPv6-dır. IPv4 şəbəkələrindən Session Pooler istifadə edin —
 * bax docs/database_deployment.md.
 */
const fs = require('node:fs');
const path = require('node:path');
const { Client } = require('pg');

const [, , sqlPath, kompasosEnv = 'DEV'] = process.argv;
if (!sqlPath) {
  console.error('İstifadə: node scripts/db/apply.js <fayl.sql> [DEV|STAGING|PRODUCTION]');
  process.exit(2);
}

function buildClientConfig() {
  if (process.env.DATABASE_URL) {
    return {
      connectionString: process.env.DATABASE_URL,
      ssl: { rejectUnauthorized: false },
      connectionTimeoutMillis: 15000,
    };
  }
  const { SB_HOST, SB_REF, SB_PASSWORD, SB_PORT = '5432' } = process.env;
  if (!SB_HOST || !SB_REF || !SB_PASSWORD) {
    console.error(
      'DATABASE_URL, və ya SB_HOST + SB_REF + SB_PASSWORD mühit dəyişənləri lazımdır'
    );
    process.exit(2);
  }
  return {
    host: SB_HOST,
    port: Number(SB_PORT),
    user: `postgres.${SB_REF}`,
    password: SB_PASSWORD,
    database: process.env.SB_DATABASE || 'postgres',
    ssl: { rejectUnauthorized: false },
    connectionTimeoutMillis: 15000,
  };
}

/** psql meta-əmrlərini çıxarır və psql dəyişənlərini əvəz edir. */
function preprocess(sql, env) {
  const lines = sql.split(/\r?\n/).map((line) => {
    const trimmed = line.trim();
    // \set, \if, \else, \endif — psql-ə xasdır, serverdə mənası yoxdur
    return trimmed.startsWith('\\') ? `-- [psql meta silindi] ${trimmed}` : line;
  });
  return lines.join('\n').replace(/:'kompasos_env'/g, `'${env}'`);
}

(async () => {
  const absolute = path.resolve(sqlPath);
  const raw = fs.readFileSync(absolute, 'utf8');
  const sql = preprocess(raw, kompasosEnv);

  const client = new Client(buildClientConfig());
  const notices = [];
  client.on('notice', (msg) => notices.push(`${msg.severity}: ${msg.message}`));

  console.log(`\n=== ${path.basename(absolute)} (env=${kompasosEnv}) ===`);
  console.log(`    ${raw.split(/\r?\n/).length} sətir, ${(raw.length / 1024).toFixed(1)} KB`);

  const started = Date.now();
  try {
    await client.connect();
    await client.query(sql);
    console.log(`\n✅ UĞURLU — ${((Date.now() - started) / 1000).toFixed(1)} s`);
  } catch (err) {
    console.error(`\n❌ XƏTA: ${err.message}`);
    if (err.position) {
      const lineNo = sql.slice(0, Number(err.position)).split('\n').length;
      const from = Math.max(0, lineNo - 4);
      console.error(`   Emal edilmiş faylda sətir ~${lineNo}:`);
      sql.split('\n').slice(from, lineNo + 3).forEach((l, i) => {
        const n = from + i + 1;
        console.error(`   ${n === lineNo ? '>>' : '  '} ${n}: ${l}`);
      });
    }
    if (err.detail) console.error(`   Detal: ${err.detail}`);
    if (err.hint) console.error(`   Tövsiyə: ${err.hint}`);
    if (err.where) console.error(`   Yer: ${err.where}`);
    process.exitCode = 1;
  } finally {
    if (notices.length) {
      console.log(`\n--- Server mesajları (${notices.length}) ---`);
      for (const n of notices) console.log(`   ${n}`);
    }
    try { await client.end(); } catch { /* ignore */ }
  }
})();
