#!/usr/bin/env node
/**
 * Sürətli SQL sorğu icraçısı (diaqnostika üçün).
 *
 *     node scripts/db/query.js "SELECT count(*) FROM kompasos.employees"
 *     node scripts/db/query.js --file some_query.sql
 *
 * Bağlantı: `apply.js` ilə eyni mühit dəyişənləri.
 */
const fs = require('node:fs');
const { Client } = require('pg');

const args = process.argv.slice(2);
let sql;
if (args[0] === '--file') {
  sql = fs.readFileSync(args[1], 'utf8');
} else {
  sql = args.join(' ');
}
if (!sql?.trim()) {
  console.error('İstifadə: node scripts/db/query.js "<SQL>" | --file <fayl.sql>');
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
    console.error('DATABASE_URL, və ya SB_HOST + SB_REF + SB_PASSWORD lazımdır');
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

(async () => {
  const client = new Client(buildClientConfig());
  client.on('notice', (m) => console.log(`   ${m.severity}: ${m.message}`));
  try {
    await client.connect();
    const result = await client.query(sql);
    const results = Array.isArray(result) ? result : [result];
    for (const r of results) {
      if (r.rows?.length) console.table(r.rows);
      else console.log(`OK (${r.command ?? ''} ${r.rowCount ?? 0} sətir)`);
    }
  } catch (err) {
    console.error(`XƏTA: ${err.message}`);
    if (err.detail) console.error(`Detal: ${err.detail}`);
    process.exitCode = 1;
  } finally {
    try { await client.end(); } catch { /* ignore */ }
  }
})();
