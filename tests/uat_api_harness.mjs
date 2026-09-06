// CrypTX — UAT API Capabilities Tester (v2)
// Probes every OpenAPI operation. Uses generic {param} substitution + a skip-list
// for auth endpoints that mutate/clobber the active session. Writes JSON results.
import fs from 'node:fs';
import http from 'node:http';

const BASE = { host: '127.0.0.1', port: 8000 };

// Fresh login at start so the harness always runs with a live session.
async function freshLogin() {
  const body = JSON.stringify({ email: 'uat@cryptx.test', password: 'UAT-Test-2026!' });
  return new Promise((resolve, reject) => {
    const data = Buffer.from(body);
    const r = http.request({ ...BASE, path: '/api/auth/login', method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': data.length } }, res => {
      let b = ''; res.on('data', c => b += c); res.on('end', () => { const j = JSON.parse(b); resolve(j.access_token); });
    });
    r.on('error', reject); r.write(data); r.end();
  });
}
let TOKEN = await freshLogin();
fs.writeFileSync(new URL('../.uat_token.txt', import.meta.url), TOKEN);

const spec = JSON.parse(fs.readFileSync(new URL('../openapi.json', import.meta.url), 'utf8'));

const ADDR = {
  bybit: '0x47666fab8bd0ac7003bce3f5c3585383f09486e2',
  lazarus: '0x098B716B8Aaf21512996dC57EB0615e2383E2f96',
  tornadoRtr: '0x722122dF12D4e14e13Ac3b6895a86e84145b6967',
  tornado01: '0x12D66f87A04A9E220743712cE6d9bB1B5616B8Fc',
  thorchain: '0xC145990E84155416144C532E31f89b840Ca8c2cE',
  binance: '0x28C6c06298d514Db089934071355E5743bf21d60',
  vitalik: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
  usdt: '0xdAC17F958D2ee523a2206206994597C13D831ec7',
  uniswapRtr: '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
  btcRansom: 'bc1q5shngj24323nsrmxv99652zqqvcpxszqp86wm4',
};
const DEMO_CASE = 'demo0000-0000-4000-a000-embe4f0463e0';
const FAKE_UUID = '00000000-0000-4000-a000-000000000000';
const DEMO_TX = '0x09b57c4f6c5e4f4a9c0b8e7d6a3f2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5';

// Endpoints that would clobber the active test session or permanently mutate auth
// state. We skip them (they're exercised by dedicated auth tests instead).
const SKIP_PATHS = new Set([
  '/api/auth/logout', '/api/auth/logout-all', '/api/auth/change-password',
  '/api/auth/forgot-password', '/api/auth/reset-password', '/api/auth/register',
  '/api/auth/sessions/{session_id}', // revokes a session
]);

// Endpoints that do live web scraping (Arkham/DeBank/Etherscan/TheGraph) and can
// legitimately take 1-3 min on a cold cache or under rate-limiting. Probed in a
// separate "slow tier" pass with a long timeout so they don't dominate the run.
const SLOW_PATHS = [
  '/api/address', '/api/sanctions', '/api/arkham/', '/api/debank/', '/api/attribution-analysis',
  '/api/ens/', '/api/trace', '/api/dex', '/api/risk-score', '/api/forensics/analyze',
  '/api/threat-intel/analyze', '/api/nexus/', '/api/identity/', '/api/cashout/detect',
  '/api/crosschain/', '/api/cluster/', '/api/case-qa/', '/api/agent/case/',
  '/api/holistic/', '/api/perp-dex/', '/api/predict', '/api/insights', '/api/auto/start',
  '/api/entity/investigate', '/api/defi/analyze', '/api/timetravel/', '/api/tx-investigate/',
  '/api/tx', '/api/laundering/', '/api/contract/', '/api/demix/', '/api/scam-infra/',
  '/api/osint-sweep/', '/api/public-enrichment/', '/api/sanctions/refresh', '/api/feeds/sync',
  '/api/nft-tron/', '/api/recovery/route', '/api/recovery/preview',
];
const isSlow = (p) => SLOW_PATHS.some(s => p.startsWith(s));

function req(method, path, { body, expectAuth = true, headers = {}, timeout } = {}) {
  return new Promise((resolve) => {
    const data = body ? Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)) : null;
    const hdrs = { ...headers };
    if (data) { hdrs['Content-Type'] = hdrs['Content-Type'] || 'application/json'; hdrs['Content-Length'] = data.length; }
    if (expectAuth) hdrs['Authorization'] = `Bearer ${TOKEN}`;
    const start = Date.now();
    const to = timeout || (isSlow(path) ? 180000 : 25000);
    const r = http.request({ ...BASE, path, method, headers: hdrs, timeout: to }, (res) => {
      let buf = '';
      res.on('data', c => buf += c);
      res.on('end', () => {
        const ms = Date.now() - start;
        let parsed = buf;
        try { parsed = buf ? JSON.parse(buf) : ''; } catch { /* keep raw */ }
        resolve({ status: res.statusCode, ms, body: parsed, rawLen: buf.length });
      });
    });
    r.on('error', e => resolve({ status: 0, ms: Date.now() - start, error: String(e), body: null }));
    r.on('timeout', () => { r.destroy(); resolve({ status: 0, ms: to, error: 'TIMEOUT', body: null }); });
    if (data) r.write(data);
    r.end();
  });
}

// Generic {param} substitution. Heuristic per param name; default = fake UUID.
function fillPath(pathTemplate) {
  return pathTemplate.replace(/\{([a-z_]+)\}/gi, (m, name) => {
    const n = name.toLowerCase();
    if (n.includes('addr')) return ADDR.bybit;
    if (n === 'address') return ADDR.bybit;
    if (n.includes('chain')) return 'eth';
    if (n.includes('hash') || n === 'tx') return DEMO_TX;
    if (n.includes('case')) return DEMO_CASE;
    if (n.includes('token') || n.includes('share')) return 'nonexistent-token-xyz';
    if (n.includes('vasp')) return 'binance';
    if (n.includes('uid') || n === 'entity') return FAKE_UUID;
    if (n.includes('symbol') || n.includes('ticker')) return 'eth';
    if (n.includes('item')) return '0';
    return FAKE_UUID;
  });
}

function defaultBody(method, path) {
  if (method !== 'post' && method !== 'put' && method !== 'patch') return undefined;
  const p = path.toLowerCase();
  if (p.endsWith('/auth/login')) return { email: 'uat@cryptx.test', password: 'UAT-Test-2026!' };
  if (p.endsWith('/auth/refresh')) return { refresh_token: 'invalid' };
  if (p.endsWith('/auth/profile')) return { name: 'UAT Tester' };
  if (p.endsWith('/auth/users/{user_id}/role')) return { role: 'analyst' };
  if (p.endsWith('/auth/users/{user_id}/active')) return { is_active: true };
  if (p.endsWith('/address') || p.endsWith('/risk-score') || p.endsWith('/sanctions') || p.endsWith('/sanctions/screen'))
    return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/batch/screen')) return { addresses: [ADDR.lazarus, ADDR.tornado01, ADDR.binance, ADDR.vitalik], chains: ['eth'] };
  if (p.includes('/trace')) return { address: ADDR.bybit, chain: 'eth', hops: 2, direction: 'out' };
  if (p.includes('/holistic')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.includes('/nexus')) return { address: ADDR.bybit, chain: 'eth', hops: 2 };
  if (p.endsWith('/dex')) return { address: ADDR.uniswapRtr, chain: 'eth' };
  if (p.includes('/forensics/analyze')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.includes('/tx') && !p.includes('interpret')) return { chain: 'eth', tx_hash: DEMO_TX };
  if (p.includes('/monitor/watches')) return { address: ADDR.bybit, chain: 'eth', label: 'UAT watch' };
  if (p.endsWith('/evidence/{case_id}')) return { evidence_type: 'screenshot', title: 'UAT evidence', content: { address: ADDR.bybit }, subject: ADDR.bybit, chain: 'eth', tags: ['uat'], analyst_notes: 'auto' };
  if (p.endsWith('/cases')) return { name: 'UAT auto-case', description: 'created by harness' };
  if (p.includes('/cases/') && p.includes('/addresses')) return { address: ADDR.vitalik, chain: 'eth' };
  if (p.includes('/cases/') && p.includes('/notes')) return { note: 'UAT note' };
  if (p.includes('/cases/') && p.includes('/members')) return { email: 'uat@cryptx.test' };
  if (p.endsWith('/attribution')) return { address: ADDR.binance, chain: 'eth' };
  if (p.endsWith('/attribution-submissions')) return { address: ADDR.binance, chain: 'eth', entity: 'Binance', evidence_note: 'auto' };
  if (p.endsWith('/regulatory/sar')) return { case_id: DEMO_CASE };
  if (p.endsWith('/regulatory/ctr')) return { case_id: DEMO_CASE };
  if (p.endsWith('/regulatory/travel-rule')) return { case_id: DEMO_CASE };
  if (p.includes('/reports/generate')) return { case_id: DEMO_CASE, audience: 'investigator' };
  if (p.endsWith('/contract/scan')) return { source: 'function setFee(uint256 x) external onlyOwner { sellFee = x; }' };
  if (p.endsWith('/contract/approvals')) return { approvals: [{ token_symbol: 'USDT', spender: '0xBadRouter', amount: 'infinite' }], malicious_spenders: ['0xbadrouter'] };
  if (p.endsWith('/contract/compare')) return { bytecode_a: '0x608060', bytecode_b: '0x608060' };
  if (p.endsWith('/contract/incident')) return { contract: ADDR.usdt, attacker: ADDR.lazarus, txs: [] };
  if (p.endsWith('/contract/fingerprint')) return { bytecode: '0x608060' };
  if (p.endsWith('/laundering/poisoning')) return { subject: ADDR.vitalik, transfers: [] };
  if (p.endsWith('/laundering/swap-trace')) return { subject: ADDR.vitalik, transfers: [], candidate_outputs: [] };
  if (p.endsWith('/laundering/typologies')) return { subject: ADDR.vitalik, transfers: [] };
  if (p.endsWith('/daubert/dossier')) return { case_ref: 'UAT-001', analyst: 'UAT Tester', methods: ['clustering'] };
  if (p.endsWith('/daubert/dossier/html')) return { case_ref: 'UAT-001', analyst: 'UAT Tester', methods: ['clustering'] };
  if (p.endsWith('/daubert/notarize')) return { case_ref: 'UAT-001', exhibit_id: 'ex1', content: 'test' };
  if (p.endsWith('/daubert/verify-chain')) return { case_ref: 'UAT-001' };
  if (p.endsWith('/daubert/benchmark/run')) return { method: 'clustering', n: 5 };
  if (p.endsWith('/recovery/preview') || p.endsWith('/recovery/requests')) return { address: ADDR.lazarus, chain: 'trx', asset: 'USDT', amount: '250000', reason: 'UAT test' };
  if (p.includes('/recovery/requests/') && p.endsWith('/status')) return { status: 'submitted' };
  if (p.includes('/comply/programs') && !p.includes('addresses') && !p.includes('screen') && !p.includes('transfer'))
    return p.endsWith('/programs') ? { name: 'UAT program', chain: 'eth', asset: 'USDT' } : {};
  if (p.includes('/comply/programs/') && p.includes('/addresses')) return { address: ADDR.usdt, chain: 'eth' };
  if (p.includes('/comply/programs/') && p.endsWith('/screen')) return {};
  if (p.includes('/comply/programs/') && p.includes('/transfers')) return { from: ADDR.vitalik, to: ADDR.binance, amount: '100', chain: 'eth' };
  if (p.includes('/freeze-net/watches')) return { address: ADDR.lazarus, chain: 'trx', asset: 'USDT' };
  if (p.endsWith('/freeze-net/scan')) return { address: ADDR.lazarus, chain: 'trx' };
  if (p.endsWith('/scam-infra/networks/{nid}/promote')) return { note: 'UAT' };
  if (p.endsWith('/perp-dex')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/predict')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/predict/train') || p.endsWith('/predict/baselines')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/insights')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.includes('/ai/') && (p.includes('chat') || p.includes('ask'))) return { case_id: DEMO_CASE, message: 'Summarize this case' };
  if (p.includes('/ai/')) return { case_id: DEMO_CASE, address: ADDR.bybit, chain: 'eth' };
  if (p.includes('/agent/case/') && p.endsWith('/chat')) return { message: 'Summarize this case' };
  if (p.includes('/agent/case/') && p.endsWith('/action')) return { action: 'cashout', address: ADDR.bybit, chain: 'eth' };
  if (p.includes('/case-qa/') && p.endsWith('/ask')) return { question: 'What addresses are involved?' };
  if (p.endsWith('/victim-reports')) return { scam_type: 'pig_butchering', scammer_address: ADDR.bybit, amount_usd: 25000, chain: 'eth' };
  if (p.includes('/victim-reports/') && p.endsWith('/confirm-label')) return { label: 'scam' };
  if (p.endsWith('/boards') || p.endsWith('/boards/')) return { title: 'UAT board' };
  if (p.includes('/boards/') && p.endsWith('/folders')) return { name: 'UAT folder' };
  if (p.includes('/boards/') && p.includes('/comments')) return { text: 'UAT comment' };
  if (p.includes('/boards/') && p.endsWith('/links')) return { target_board_id: FAKE_UUID, note: 'UAT' };
  if (p.includes('/boards/') && p.endsWith('/share')) return { mode: 'view' };
  if (p.endsWith('/labels') || p.endsWith('/labels/import')) return { address: ADDR.binance, chain: 'eth', label: 'Binance 14 (hot)' };
  if (p.includes('/osint-sweep/') && p.endsWith('/to-evidence')) return { case_id: DEMO_CASE };
  if (p.includes('/osint-sweep')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.includes('/portal/victim-report')) return { scam_type: 'pig_butchering', scammer_address: ADDR.bybit, amount_usd: 25000, chain: 'eth' };
  if (p.includes('/collaboration/join')) return { room: 'UAT-room' };
  if (p.includes('/collaboration/heartbeat')) return { room: 'UAT-room' };
  if (p.includes('/collaboration/lock')) return { room: 'UAT-room', key: 'x' };
  if (p.includes('/collaboration/unlock')) return { room: 'UAT-room' };
  if (p.includes('/ingestion/import-json')) return { case_id: DEMO_CASE, records: [] };
  if (p.includes('/ingestion/') && p.endsWith('/review')) return { decision: 'accept' };
  if (p.includes('/feeds/diff-alerts/') && p.endsWith('/review')) return { decision: 'accept' };
  if (p.endsWith('/exports/stix')) return { addresses: [ADDR.bybit], chain: 'eth' };
  if (p.endsWith('/exports/misp')) return { addresses: [ADDR.bybit], chain: 'eth' };
  if (p.endsWith('/exports/fincen-xml')) return { case_id: DEMO_CASE };
  if (p.endsWith('/exports/pdf') || p.endsWith('/exports/docx')) return { case_id: DEMO_CASE, title: 'UAT' };
  if (p.endsWith('/prices/convert')) return { amount: '1', from: 'eth', to: 'usd' };
  if (p.endsWith('/investigations')) return { subject: ADDR.bybit, chain: 'eth', case_id: DEMO_CASE };
  if (p.includes('/investigations/') && p.endsWith('/expand')) return { addresses: [ADDR.binance] };
  if (p.endsWith('/demix/tornado')) return { deposits: [], withdrawals: [] };
  if (p.endsWith('/demix/bridge')) return { source_locks: [], dest_mints: [] };
  if (p.endsWith('/demix/mixer')) return { inputs: [], outputs: [] };
  if (p.endsWith('/demix/chain-swap')) return { inputs: [], outputs: [] };
  if (p.endsWith('/demix/analyze')) return { events: [] };
  if (p.endsWith('/entity/investigate')) return { addresses: [ADDR.bybit, ADDR.lazarus], chains: ['eth'] };
  if (p.endsWith('/timetravel/reconstruct')) return { address: ADDR.bybit, chain: 'eth', timestamp: 1710000000 };
  if (p.endsWith('/timetravel/evolution')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/defi/analyze')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/cluster/analyze')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/cashout/detect')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/tx/interpret')) return { chain: 'eth', tx_hash: DEMO_TX };
  if (p.endsWith('/crosschain/trace')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/timeline/build')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/tx-investigate/analyze')) return { chain: 'eth', tx_hash: DEMO_TX };
  if (p.endsWith('/tx-investigate/jobs')) return { chain: 'eth', tx_hash: DEMO_TX };
  if (p.endsWith('/nexus/paths')) return { address: ADDR.bybit, chain: 'eth', target: ADDR.binance };
  if (p.endsWith('/nexus/demix')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/threat-intel/analyze')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/identity/profile')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/arkham/lookup')) return { address: ADDR.bybit };
  if (p.endsWith('/debank/owner')) return { address: ADDR.bybit };
  if (p.endsWith('/ens/resolve')) return { name: 'vitalik.eth' };
  if (p.endsWith('/ens/reverse')) return { address: ADDR.vitalik };
  if (p.endsWith('/attribution-analysis')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/feeds/sync')) return {};
  if (p.endsWith('/public-enrichment/address')) return { address: ADDR.bybit, chain: 'eth' };
  if (p.endsWith('/public-enrichment/refresh')) return {};
  if (p.endsWith('/sanctions/screen-bulk')) return { addresses: [ADDR.lazarus, ADDR.vitalik], chains: ['eth'] };
  if (p.endsWith('/sanctions/search')) return { query: 'Lazarus Group' };
  if (p.endsWith('/sanctions/refresh')) return {};
  if (p.endsWith('/kyv')) return { name: 'Binance' };
  if (p.endsWith('/monitor/scan')) return {};
  if (p.endsWith('/monitor/rules')) return { name: 'UAT rule', category: 'mixer', direction: 'any' };
  if (p.includes('/monitor/notifications/') && p.endsWith('/read')) return {};
  if (p.endsWith('/monitor/destinations')) return { type: 'webhook', target: 'https://example.com/hook' };
  return {};
}

const allOps = [];
for (const [path, methods] of Object.entries(spec.paths)) {
  for (const [m, op] of Object.entries(methods)) {
    if (!op || typeof op !== 'object') continue;
    allOps.push({ method: m.toUpperCase(), path, op });
  }
}
console.log(`Probing ${allOps.length} operations (token len ${TOKEN.length})…`);

// CLI flags: `--fast` skips slow live-scrape endpoints; `--slow` runs ONLY them.
const ARGS = new Set(process.argv.slice(2));
const ONLY_SLOW = ARGS.has('--slow');
const SKIP_SLOW = ARGS.has('--fast');

const results = [];
let loginFailures = 0;
for (const { method, path, op } of allOps) {
  if (SKIP_PATHS.has(path)) {
    results.push({ method, path, tag: (op.tags || []).join(','), opId: op.operationId || '', status: -1, ms: 0, cls: 'skipped', err: 'stateful auth endpoint', slow: false });
    continue;
  }
  const filledPreview = path.replace(/\{([a-z_]+)\}/gi, (m, n) => n.toLowerCase().includes('addr') ? '0x47666fab8bd0ac7003bce3f5c3585383f09486e2' : 'x');
  // spec paths already include the /api prefix, so check isSlow directly.
  if (SKIP_SLOW && isSlow(filledPreview)) {
    results.push({ method, path: filledPreview, tag: (op.tags || []).join(','), opId: op.operationId || '', status: -1, ms: 0, cls: 'skipped_slow', err: 'slow tier (run with --slow)', slow: true });
    continue;
  }
  if (ONLY_SLOW && !isSlow(filledPreview)) {
    results.push({ method, path: filledPreview, tag: (op.tags || []).join(','), opId: op.operationId || '', status: -1, ms: 0, cls: 'skipped_fast', err: 'fast tier (run with --fast)', slow: false });
    continue;
  }
  const filled = fillPath(path);
  const slow = isSlow(filled);
  let r = await req(method.toLowerCase(), filled, { body: defaultBody(method.toLowerCase(), filled) });
  // Auto re-login on any 401 (except the login endpoint itself) so a stale/expired
  // token never poisons the rest of the run.
  if (r.status === 401 && path !== '/api/auth/login' && loginFailures < 5) {
    try { TOKEN = await freshLogin(); loginFailures = 0; }
    catch { loginFailures++; }
    r = await req(method.toLowerCase(), filled, { body: defaultBody(method.toLowerCase(), filled) });
  }
  let cls;
  if (r.status === 0) cls = 'network';
  else if (r.status < 300) cls = 'ok';
  else if (r.status === 401 || r.status === 403) cls = 'auth';
  else if (r.status === 404) cls = 'not_found';
  else if (r.status === 400 || r.status === 409 || r.status === 422) cls = 'client';
  else if (r.status === 429) cls = 'rate';
  else if (r.status >= 500) cls = 'server';
  else cls = `other_${r.status}`;
  const errSnippet = (cls !== 'ok' && cls !== 'skipped' && r.body) ? (typeof r.body === 'object' ? JSON.stringify(r.body).slice(0, 300) : String(r.body).slice(0, 300)) : '';
  results.push({ method, path: filled, tag: (op.tags || []).join(','), opId: op.operationId || '', status: r.status, ms: r.ms, cls, err: errSnippet, slow });
  if (cls === 'server' || cls === 'network') console.log(`  [${cls}] ${method} ${filled} → ${r.status} (${r.ms}ms) ${errSnippet.slice(0, 140)}`);
}

const byClass = {};
for (const r of results) byClass[r.cls] = (byClass[r.cls] || 0) + 1;
const fails = results.filter(r => ['server', 'network', 'client', 'not_found', 'auth', 'rate'].includes(r.cls));

const tierSuffix = ONLY_SLOW ? '_slow' : (SKIP_SLOW ? '_fast' : '');
fs.writeFileSync(new URL(`../UAT_API_RESULTS${tierSuffix}.json`, import.meta.url), JSON.stringify(results, null, 2));

console.log('\n=== SUMMARY ===');
console.log('Total ops probed:', results.length, '(skipped:', byClass.skipped || 0, ')');
console.log('By class:', JSON.stringify(byClass, null, 2));
console.log('Fails:', fails.length, '(client/not_found are often expected for placeholder IDs)');
const critical = fails.filter(r => ['server', 'network'].includes(r.cls));
console.log('CRITICAL (server/network):', critical.length);
for (const f of critical) console.log(`   [${f.cls}] ${f.method} ${f.path} → ${f.status}  ${f.err.slice(0,140)}`);
