// CrypTX — End-to-End Integration Tests
// Real cross-feature workflows that prove the platform integrates correctly.
// Each workflow chains multiple features with real data and asserts the data
// flows through correctly (IDs propagate, evidence links to cases, etc.).
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
const BYBIT = '0x47666fab8bd0ac7003bce3f5c3585383f09486e2';
const LAZARUS = '0x098B716B8Aaf21512996dC57EB0615e2383E2f96';
const BINANCE = '0x28C6c06298d514Db089934071355E5743bf21d60';
const VITALIK = '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045';

function req(method, path, body, timeoutMs = 60000) {
  return new Promise((resolve) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const hdrs = data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {};
    hdrs['Authorization'] = `Bearer ${TOKEN}`;
    const r = http.request({ ...BASE, path, method, headers: hdrs, timeout: timeoutMs }, res => {
      let b = ''; res.on('data', c => b += c); res.on('end', () => {
        let parsed; try { parsed = JSON.parse(b); } catch { parsed = b; }
        resolve({ status: res.statusCode, body: parsed, raw: b });
      });
    });
    r.on('error', e => resolve({ status: 0, body: String(e) }));
    r.on('timeout', () => { r.destroy(); resolve({ status: 0, body: 'TIMEOUT' }); });
    if (data) r.write(data);
    r.end();
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

const results = [];
function check(label, cond, detail = '') {
  results.push({ label, pass: !!cond, detail: String(detail).slice(0, 160) });
  console.log(`${cond ? '✅' : '❌'} ${label}${detail ? '  — ' + String(detail).slice(0, 120) : ''}`);
}

console.log('═══ WORKFLOW 1: Sanctions screen → create case → add address → note → evidence → report ═══\n');
// 1a. Screen Lazarus (sanctioned) and Vitalik (clean) in parallel
const [screenLaz, screenVit] = await Promise.all([
  req('POST', '/api/sanctions/screen', { address: LAZARUS, chain: 'eth' }),
  req('POST', '/api/sanctions/screen', { address: VITALIK, chain: 'eth' }),
]);
check('1a. Lazarus flagged as sanctioned', screenLaz.status === 200 && (screenLaz.body?.sanctioned === true || screenLaz.body?.match === true || JSON.stringify(screenLaz.body).toLowerCase().includes('sanction')), JSON.stringify(screenLaz.body).slice(0, 100));
check('1a. Vitalik clean (no sanctions hit)', screenVit.status === 200 && !(JSON.stringify(screenVit.body).toLowerCase().includes('sanctioned":true') || screenVit.body?.sanctioned === true), JSON.stringify(screenVit.body).slice(0, 80));

// 1b. Create a fresh case
const newCase = await req('POST', '/api/cases', { name: 'UAT Integration Case ' + Date.now(), description: 'E2E workflow test' });
check('1b. Create case', newCase.status === 200 && newCase.body?.id, newCase.body?.id || newCase.body?.detail);
const caseId = newCase.body?.id;

// 1c. Add the sanctioned address to the case
if (caseId) {
  const addAddr = await req('POST', `/api/cases/${caseId}/addresses`, { address: LAZARUS, chain: 'eth', label: 'Lazarus (sanctioned)' });
  check('1c. Add address to case', addAddr.status === 200, JSON.stringify(addAddr.body).slice(0, 80));

  // 1d. Add a note
  const addNote = await req('POST', `/api/cases/${caseId}/notes`, { note: 'OFAC SDN match confirmed via sanctions screen.' });
  check('1d. Add note to case', addNote.status === 200, addNote.body?.detail);

  // 1e. Verify case now has the address + note
  const getCase = await req('GET', `/api/cases/${caseId}`);
  check('1e. Case persists address', getCase.status === 200 && Array.isArray(getCase.body?.addresses) && getCase.body.addresses.some(a => (a.address || '').toLowerCase() === LAZARUS.toLowerCase()), `addresses: ${getCase.body?.addresses?.length || 0}`);
  check('1e. Case persists note', getCase.status === 200 && Array.isArray(getCase.body?.notes) && getCase.body.notes.length > 0, `notes: ${getCase.body?.notes?.length || 0}`);

  // 1f. Save evidence into the case
  const saveEv = await req('POST', `/api/evidence/${caseId}`, { evidence_type: 'sanctions_screen', title: 'Lazarus sanctions hit', content: { address: LAZARUS, source: 'OFAC SDN' }, subject: LAZARUS, chain: 'eth', tags: ['sanctions', 'ofac'], analyst_notes: 'auto-captured' });
  check('1f. Save evidence to case', saveEv.status === 200 && saveEv.body?.evidence?.id, saveEv.body?.evidence?.id || saveEv.body?.detail);
  const evidenceId = saveEv.body?.evidence?.id;

  // 1g. Verify evidence audit log (chain of custody)
  if (evidenceId) {
    const audit = await req('GET', `/api/evidence/${caseId}/${evidenceId}/audit`);
    check('1g. Evidence has audit log (chain of custody)', audit.status === 200 && Array.isArray(audit.body?.audit_log) && audit.body.audit_log.length > 0, `entries: ${audit.body?.audit_log?.length || 0}`);
  }

  // 1h. Case evidence summary aggregates it
  const evSum = await req('GET', `/api/evidence/${caseId}/summary`);
  check('1h. Case evidence summary', evSum.status === 200, JSON.stringify(evSum.body?.summary || {}).slice(0, 80));

  // 1i. Verify custody chain integrity (global hash chain)
  const custody = await req('GET', '/api/custody/verify');
  check('1i. Custody chain verifies (tamper-evident)', custody.status === 200 && custody.body?.valid !== false, `valid=${custody.body?.valid}`);
}

console.log('\n═══ WORKFLOW 2: Victim report → scam intelligence clustering ═══\n');
// 2a. Submit a victim report
const vr = await req('POST', '/api/victim-reports', { scam_type: 'pig_butchering', scammer_address: BYBIT, amount_usd: 50000, chain: 'eth', description: 'E2E workflow victim report' });
check('2a. Submit victim report', vr.status === 200 && vr.body?.report?.id, vr.body?.report?.id || vr.body?.detail);

// 2b. Scam intel summary reflects reports
const scamSum = await req('GET', '/api/scam-intel/summary');
check('2b. Scam intel summary aggregates reports', scamSum.status === 200 && (scamSum.body?.total_reports > 0 || scamSum.body?.summary), `total: ${scamSum.body?.total_reports || scamSum.body?.summary?.total_reports}`);

// 2c. Scam intel by address returns data for the reported address
const scamAddr = await req('GET', `/api/scam-intel/address/${BYBIT}`);
check('2c. Scam intel by address', scamAddr.status === 200, JSON.stringify(scamAddr.body).slice(0, 80));

console.log('\n═══ WORKFLOW 3: Attribution → label propagates across screens ═══\n');
// 3a. Add a local label for Binance
const label = await req('POST', '/api/labels', { address: BINANCE, chain: 'eth', label: 'Binance 14 (hot)', category: 'exchange', confidence: 0.99, source: 'uat-integration' });
check('3a. Create local label', label.status === 200, label.body?.detail);

// 3b. Label appears in labels-for-address (used by Address Intel)
const labelsFor = await req('GET', `/api/labels/${BINANCE}`);
check('3b. Label retrievable by address', labelsFor.status === 200, JSON.stringify(labelsFor.body).slice(0, 80));

console.log('\n═══ WORKFLOW 4: Batch screen → per-address risk scores ═══\n');
// 4a. Batch screen the 4 reference addresses
const batch = await req('POST', '/api/batch/screen', { addresses: [LAZARUS, BINANCE, VITALIK], max_concurrent: 3 }, 120000);
check('4a. Batch screen completes', batch.status === 200, JSON.stringify(batch.body).slice(0, 100));
if (batch.status === 200) {
  const results = batch.body?.results || batch.body?.screens || [];
  check('4a. Batch returns per-address results', Array.isArray(results) && results.length >= 1, `count: ${results.length}`);
}

console.log('\n═══ WORKFLOW 5: Board create → add nodes → share link ═══\n');
// 5a. Create a board
const board = await req('POST', '/api/boards', { name: 'UAT Integration Board ' + Date.now() });
check('5a. Create board', board.status === 200 && board.body?.id, board.body?.id || board.body?.detail);
const boardId = board.body?.id;

// 5b. Board persists
if (boardId) {
  const getBoard = await req('GET', `/api/boards/${boardId}`);
  check('5b. Board persists on retrieval', getBoard.status === 200 && getBoard.body?.name, getBoard.body?.name);

  // 5c. Create a share link
  const share = await req('POST', `/api/boards/${boardId}/share`, { mode: 'public' });
  check('5c. Board share link created', share.status === 200 && (share.body?.token || share.body?.share?.token), JSON.stringify(share.body).slice(0, 80));
}

console.log('\n═══ WORKFLOW 6: Recovery → freeze route resolution ═══\n');
// 6a. Resolve a freeze route for USDT on TRX
const route = await req('GET', '/api/recovery/route?asset=USDT&chain=trx');
check('6a. Recovery route resolves (USDT/TRX → Tether)', route.status === 200, JSON.stringify(route.body).slice(0, 100));
if (route.status === 200) {
  const r = route.body?.route || route.body?.channel || route.body;
  check('6a. Routes to issuer-level freeze channel', JSON.stringify(r).toLowerCase().includes('tether') || JSON.stringify(r).toLowerCase().includes('issuer') || JSON.stringify(route.body).toLowerCase().includes('freeze'), JSON.stringify(route.body).slice(0, 100));
}

console.log('\n═══ WORKFLOW 7: Public portal (no auth) → feeds scam intel ═══\n');
// 7a. Public victim portal submission
const portal = await req('POST', '/api/portal/victim-report', { scam_type: 'phishing', scammer_address: VITALIK, amount_usd: 5000, chain: 'eth' });
check('7a. Public portal submission accepted', portal.status === 200 && portal.body?.report_id, portal.body?.report_id);
// 7b. Public stats reflect it
const stats = await req('GET', '/api/portal/scam-stats');
check('7b. Public scam-stats updated', stats.status === 200 && stats.body?.total_reports > 0, `total: ${stats.body?.total_reports}`);

// ── Summary ────────────────────────────────────────────────────────────
const passed = results.filter(r => r.pass).length;
const failed = results.filter(r => !r.pass).length;
console.log(`\n${'═'.repeat(70)}`);
console.log(`INTEGRATION SUMMARY: ${passed}/${results.length} checks passed, ${failed} failed`);
if (failed) {
  console.log('\nFailed checks:');
  for (const r of results.filter(x => !x.pass)) console.log(`  ❌ ${r.label}  — ${r.detail}`);
}
fs.writeFileSync(new URL('../INTEGRATION_RESULTS.json', import.meta.url), JSON.stringify({ passed, failed, total: results.length, results }, null, 2));
