// CrypTX — Performance Concurrency Test
// Proves the async-blocking fixes work: while a CPU-heavy endpoint runs in the
// threadpool, lightweight endpoints must STILL respond quickly (they were blocked
// before the fix). Also measures baseline latency per representative endpoint.
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
const TOKEN = await login();

function req(method, path, body, timeoutMs = 60000) {
  return new Promise((resolve) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const hdrs = data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {};
    hdrs['Authorization'] = `Bearer ${TOKEN}`;
    const start = Date.now();
    const r = http.request({ ...BASE, path, method, headers: hdrs, timeout: timeoutMs }, res => {
      let b = ''; res.on('data', c => b += c); res.on('end', () => resolve({ status: res.statusCode, ms: Date.now() - start, len: b.length }));
    });
    r.on('error', e => resolve({ status: 0, ms: Date.now() - start, err: String(e) }));
    r.on('timeout', () => { r.destroy(); resolve({ status: 0, ms: timeoutMs, err: 'TIMEOUT' }); });
    if (data) r.write(data);
    r.end();
  });
}

// A non-trivial graph for the CPU endpoints (so they do real work).
const N = 12;
const nodes = Array.from({ length: N }, (_, i) => ({ id: `0x${i.toString(16).padStart(4, '0')}`, address: `0x${i.toString(16).padStart(4, '0')}`, label: i === 0 ? 'exchange' : (i === 5 ? 'mixer' : 'wallet') }));
const edges = [];
for (let i = 0; i < N - 1; i++) edges.push({ source: nodes[i].id, target: nodes[i + 1].id, value: 100 + i, timestamp: 1700000000 + i * 100 });
for (let i = 0; i < N - 3; i++) edges.push({ source: nodes[i].id, target: nodes[i + 3].id, value: 50, timestamp: 1700000100 + i });

const BYBIT = '0x47666fab8bd0ac7003bce3f5c3585383f09486e2';

// ── TEST 1: Baseline latency per representative endpoint ────────────────────
console.log('=== TEST 1: Baseline latency (single request each) ===');
const baseline = [
  { label: 'GET /health', method: 'GET', path: '/health', noAuth: true },
  { label: 'GET /api/cases', method: 'GET', path: '/api/cases' },
  { label: 'GET /api/evidence/' + '(case)', method: 'GET', path: `/api/evidence/demo0000-0000-4000-a000-embe4f0463e0` },
  { label: 'GET /api/boards', method: 'GET', path: '/api/boards' },
  { label: 'GET /api/attribution/methods', method: 'GET', path: '/api/attribution/methods' },
  { label: 'GET /api/labels', method: 'GET', path: '/api/labels' },
  { label: 'GET /api/sanctions/status', method: 'GET', path: '/api/sanctions/status' },
  { label: 'GET /api/scam-intel/scam-types', method: 'GET', path: '/api/scam-intel/scam-types' },
  { label: 'GET /api/daubert/methods', method: 'GET', path: '/api/daubert/methods' },
  { label: 'GET /api/ai/status', method: 'GET', path: '/api/ai/status' },
];
const baselineResults = [];
for (const t of baseline) {
  const r = await req(t.method, t.path);
  baselineResults.push({ ...t, status: r.status, ms: r.ms });
  console.log(`  ${t.label.padEnd(38)} ${r.status}  ${String(r.ms).padStart(5)}ms`);
}

// ── TEST 2: CPU endpoints work + their latency ─────────────────────────────
console.log('\n=== TEST 2: CPU endpoints (now offloaded) — correctness + latency ===');
const cpuTests = [
  { label: 'POST /api/nexus/paths', path: '/api/nexus/paths', body: { source_id: nodes[0].id, nodes, edges, max_hops: 8 }, expect: 200 },
  { label: 'POST /api/cluster/analyze', path: '/api/cluster/analyze', body: { nodes, edges }, expect: 200 },
  { label: 'POST /api/cashout/detect', path: '/api/cashout/detect', body: { subject_id: nodes[0].id, nodes, edges }, expect: 200 },
  { label: 'POST /api/crosschain/trace', path: '/api/crosschain/trace', body: { subject_id: nodes[0].id, nodes, edges }, expect: 200 },
  { label: 'POST /api/contract/scan', path: '/api/contract/scan', body: { source: 'function setFee(uint256 x) external onlyOwner { sellFee = x; }' }, expect: 200 },
  { label: 'POST /api/contract/approvals', path: '/api/contract/approvals', body: { approvals: [{ token_symbol: 'USDT', spender: '0xBadRouter', amount: 'infinite' }], malicious_spenders: ['0xbadrouter'] }, expect: 200 },
  { label: 'POST /api/laundering/typologies', path: '/api/laundering/typologies', body: { subject: nodes[0].id, transfers: edges.slice(0, 8).map(e => ({ from: e.source, to: e.target, value_usd: e.value, timestamp: e.timestamp })) }, expect: 200 },
  { label: 'POST /api/demix/chain-swap', path: '/api/demix/chain-swap', body: { events: edges.slice(0, 6).map(e => ({ from: e.source, to: e.target, value_usd: e.value, chain: 'eth', timestamp: e.timestamp })) }, expect: 200 },
];
const cpuResults = [];
for (const t of cpuTests) {
  const r = await req('POST', t.path, t.body, 90000);
  const ok = r.status === t.expect;
  cpuResults.push({ ...t, status: r.status, ms: r.ms, ok });
  console.log(`  ${ok ? '✅' : '❌'} ${t.label.padEnd(34)} ${r.status}  ${String(r.ms).padStart(6)}ms`);
}

// ── TEST 3: CONCURRENCY — the key proof ────────────────────────────────────
// Fire a CPU-heavy endpoint AND several fast GETs AT THE SAME TIME. Before the
// fix, the CPU call would block the event loop and the fast GETs would wait;
// after the fix, the fast GETs return in their normal ~20-40ms while the CPU
// work runs in the threadpool.
console.log('\n=== TEST 3: Concurrency under CPU load (the proof) ===');
console.log('Firing a heavy CPU endpoint + 6 fast GETs simultaneously…');
const t0 = Date.now();
const heavyPromise = req('POST', '/api/cluster/analyze', { nodes, edges }, 90000);
const fastPaths = ['/api/cases', '/api/boards', '/api/attribution/methods', '/api/labels', '/api/sanctions/status', '/api/scam-intel/scam-types'];
const fastPromises = fastPaths.map(p => req('GET', p));
const [heavy, ...fasts] = await Promise.all([heavyPromise, ...fastPromises]);
const totalMs = Date.now() - t0;
console.log(`  heavy /api/cluster/analyze:  ${heavy.status}  ${heavy.ms}ms`);
fastPaths.forEach((p, i) => console.log(`  fast  ${p.padEnd(30)} ${fasts[i].status}  ${String(fasts[i].ms).padStart(5)}ms`));
const maxFast = Math.max(...fasts.map(f => f.ms));
const fastBlocked = maxFast > 1000; // fast GETs should be <1s even under load
console.log(`\n  Total wall time: ${totalMs}ms | max fast-GET latency: ${maxFast}ms`);
console.log(`  ${fastBlocked ? '❌ FAIL — fast endpoints were blocked (event loop stalled)' : '✅ PASS — fast endpoints stayed responsive while CPU work ran offloaded'}`);

// ── Summary ────────────────────────────────────────────────────────────────
const summary = {
  baseline_avg_ms: Math.round(baselineResults.reduce((a, b) => a + b.ms, 0) / baselineResults.length),
  cpu_endpoints_pass: cpuResults.filter(c => c.ok).length + '/' + cpuResults.length,
  concurrency: { heavy_ms: heavy.ms, max_fast_ms: maxFast, passed: !fastBlocked },
};
fs.writeFileSync(new URL('../PERF_RESULTS.json', import.meta.url), JSON.stringify({ baseline: baselineResults, cpu: cpuResults, concurrency: summary }, null, 2));
console.log('\n=== SUMMARY ===');
console.log(JSON.stringify(summary, null, 2));
