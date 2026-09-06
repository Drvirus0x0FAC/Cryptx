// CrypTX — Focused post-fix verification. Tests the 6 fixed endpoints + a
// representative sample across every feature domain, with delays to keep the
// single uvicorn worker uncongested. Run: node tests/uat_verify_fixes.mjs
import fs from 'node:fs';
import http from 'node:http';

const BASE = { host: '127.0.0.1', port: 8000 };
async function login() {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ email: 'uat@cryptx.test', password: 'UAT-Test-2026!' });
    const data = Buffer.from(body);
    const r = http.request({ ...BASE, path: '/api/auth/login', method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': data.length } }, res => {
      let b = ''; res.on('data', c => b += c); res.on('end', () => resolve(JSON.parse(b).access_token));
    });
    r.on('error', reject); r.write(data); r.end();
  });
}
let TOKEN = await login();
const CASE = 'demo0000-0000-4000-a000-embe4f0463e0';
const BYBIT = '0x47666fab8bd0ac7003bce3f5c3585383f09486e2';

function req(method, path, body, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const hdrs = data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {};
    hdrs['Authorization'] = `Bearer ${TOKEN}`;
    const start = Date.now();
    const r = http.request({ ...BASE, path, method, headers: hdrs, timeout: timeoutMs }, res => {
      let b = ''; res.on('data', c => b += c); res.on('end', () => resolve({ status: res.statusCode, ms: Date.now() - start, body: b }));
    });
    r.on('error', e => resolve({ status: 0, ms: Date.now() - start, body: String(e) }));
    r.on('timeout', () => { r.destroy(); resolve({ status: 0, ms: timeoutMs, body: 'TIMEOUT' }); });
    if (data) r.write(data);
    r.end();
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Each test: { label, method, path, body, expect: status or [min,max], slow? }
const tests = [
  // ── FIXED ENDPOINTS (must pass) ──
  { fix: true, label: 'FIX1 victim portal POST', method: 'POST', path: '/api/portal/victim-report', body: { scam_type: 'pig_butchering', scammer_address: BYBIT, amount_usd: 25000, chain: 'eth' }, expect: 200 },
  { fix: true, label: 'FIX1 portal scam-stats', method: 'GET', path: '/api/portal/scam-stats', expect: 200 },
  { fix: true, label: 'FIX2 evidence PATCH (missing→404)', method: 'PATCH', path: `/api/evidence/${CASE}/00000000-0000-4000-a000-000000000000`, body: { notes: 'x' }, expect: 404 },
  { fix: true, label: 'FIX3 docx (missing case→404)', method: 'POST', path: '/api/exports/docx', body: { case_id: 'no-such-case', title: 'X' }, expect: 404 },
  { fix: true, label: 'FIX3 docx (valid case→200)', method: 'POST', path: '/api/exports/docx', body: { case_id: CASE, title: 'UAT' }, expect: 200 },
  { fix: true, label: 'FIX6 fincen-xml', method: 'POST', path: '/api/exports/fincen-xml', body: { payload: { form_type: 'SAR', case_id: CASE, subject: { address: BYBIT } } }, expect: 200 },

  // ── Representative sample across domains (sanity) ──
  { label: 'health', method: 'GET', path: '/health', expect: 200, noAuth: true },
  { label: 'auth/me', method: 'GET', path: '/api/auth/me', expect: 200 },
  { label: 'cases list', method: 'GET', path: '/api/cases', expect: 200 },
  { label: 'case detail', method: 'GET', path: `/api/cases/${CASE}`, expect: 200 },
  { label: 'evidence list', method: 'GET', path: `/api/evidence/${CASE}`, expect: 200 },
  { label: 'evidence summary', method: 'GET', path: `/api/evidence/${CASE}/summary`, expect: 200 },
  { label: 'boards list', method: 'GET', path: '/api/boards', expect: 200 },
  { label: 'sanctions status', method: 'GET', path: '/api/sanctions/status', expect: 200 },
  { label: 'sanctions screen (Vitalik=clean)', method: 'POST', path: '/api/sanctions/screen', body: { address: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045', chain: 'eth' }, expect: 200 },
  { label: 'sanctions screen (Lazarus=hit)', method: 'POST', path: '/api/sanctions/screen', body: { address: '0x098B716B8Aaf21512996dC57EB0615e2383E2f96', chain: 'eth' }, expect: 200 },
  { label: 'labels list', method: 'GET', path: '/api/labels', expect: 200 },
  { label: 'monitor watches', method: 'GET', path: '/api/monitor/watches', expect: 200 },
  { label: 'monitor rules', method: 'GET', path: '/api/monitor/rules', expect: 200 },
  { label: 'victim-reports list', method: 'GET', path: '/api/victim-reports', expect: 200 },
  { label: 'scam-intel summary', method: 'GET', path: '/api/scam-intel/summary', expect: 200 },
  { label: 'scam-intel scam-types', method: 'GET', path: '/api/scam-intel/scam-types', expect: 200 },
  { label: 'attribution methods', method: 'GET', path: '/api/attribution/methods', expect: 200 },
  { label: 'attribution lookup', method: 'GET', path: `/api/attribution/${BYBIT}`, expect: [200, 404] },
  { label: 'recovery summary', method: 'GET', path: '/api/recovery/summary', expect: 200 },
  { label: 'recovery requests', method: 'GET', path: '/api/recovery/requests', expect: 200 },
  { label: 'freeze-net directory', method: 'GET', path: '/api/freeze-net/directory', expect: 200 },
  { label: 'freeze-net kpis', method: 'GET', path: '/api/freeze-net/kpis', expect: 200 },
  { label: 'scam-infra summary', method: 'GET', path: '/api/scam-infra/summary', expect: 200 },
  { label: 'comply programs', method: 'GET', path: '/api/comply/programs', expect: 200 },
  { label: 'daubert methods', method: 'GET', path: '/api/daubert/methods', expect: 200 },
  { label: 'laundering services', method: 'GET', path: '/api/laundering/services', expect: 200 },
  { label: 'predict status', method: 'GET', path: '/api/predict/status', expect: 200 },
  { label: 'predict history', method: 'GET', path: '/api/predict/history', expect: 200 },
  { label: 'public-enrichment status', method: 'GET', path: '/api/public-enrichment/status', expect: 200 },
  { label: 'prices spot', method: 'GET', path: '/api/prices/spot?asset=eth', expect: 200 },
  { label: 'threat-feed sources', method: 'GET', path: '/api/threat-feed/sources', expect: 200 },
  { label: 'reports types', method: 'GET', path: '/api/reports/types', expect: 200 },
  { label: 'exports capabilities', method: 'GET', path: '/api/exports/capabilities', expect: 200 },
  { label: 'feeds status', method: 'GET', path: '/api/feeds/status', expect: 200 },
  { label: 'investigations list', method: 'GET', path: '/api/investigations', expect: 200 },
  { label: 'analytics counterparties', method: 'GET', path: '/api/analytics/counterparties', expect: 200 },
  { label: 'ai status', method: 'GET', path: '/api/ai/status', expect: 200 },
  { label: 'agent status', method: 'GET', path: '/api/agent/status', expect: 200 },
  { label: 'agent cases', method: 'GET', path: '/api/agent/cases', expect: 200 },
  { label: 'settings', method: 'GET', path: '/api/settings', expect: 200 },
  { label: 'kyv list', method: 'GET', path: '/api/kyv', expect: 200 },
  { label: 'regulatory sar-categories', method: 'GET', path: '/api/regulatory/sar-categories', expect: 200 },
  { label: 'custody verify', method: 'GET', path: '/api/custody/verify', expect: 200 },
];

const pass = (status, expect) => Array.isArray(expect) ? expect.includes(status) : status === expect;

let okCount = 0, failCount = 0;
const fails = [];
console.log(`Running ${tests.length} verification tests (sequential, throttled)…\n`);
for (const t of tests) {
  const r = await req(t.method, t.path, t.body, t.slow ? 120000 : 30000);
  const passed = pass(r.status, t.expect);
  if (passed) okCount++; else { failCount++; fails.push({ ...t, got: r.status, body: r.body.slice(0, 120) }); }
  const tag = t.fix ? '[FIX]' : '     ';
  console.log(`${passed ? '✅' : '❌'} ${tag} ${t.label.padEnd(34)} → ${r.status} (${r.ms}ms)${passed ? '' : '  expected ' + JSON.stringify(t.expect)}`);
  await sleep(400); // keep the single worker uncongested
}

console.log(`\n=== VERIFICATION SUMMARY ===`);
console.log(`Passed: ${okCount}/${tests.length}  |  Failed: ${failCount}`);
if (fails.length) {
  console.log('\nFailures:');
  for (const f of fails) console.log(`  ❌ ${f.label}: got ${f.got}  ${f.body}`);
}
fs.writeFileSync(new URL('../UAT_VERIFY_RESULTS.json', import.meta.url), JSON.stringify({ total: tests.length, passed: okCount, failed: failCount, fails }, null, 2));
