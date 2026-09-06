const fs = require('fs');
function load(p) { return JSON.parse(fs.readFileSync(p, 'utf8')); }
const en = load('./en/tools.json').nexusGraph;
const langs = ['fr', 'es', 'ru', 'zh'];
function flat(o, p = '') {
  let r = {};
  for (const k in o) {
    const k2 = p ? p + '.' + k : k;
    if (o[k] && typeof o[k] === 'object' && !Array.isArray(o[k])) Object.assign(r, flat(o[k], k2));
    else r[k2] = o[k];
  }
  return r;
}
const enFlat = flat(en);
console.log('EN leaf keys: ' + Object.keys(enFlat).length);
for (const l of langs) {
  const t = load('./' + l + '/tools.json').nexusGraph;
  const tFlat = flat(t);
  const missing = Object.keys(enFlat).filter(k => !(k in tFlat));
  const extra = Object.keys(tFlat).filter(k => !(k in enFlat));
  const ph = s => (String(s).match(/\{\{[^}]+\}\}/g) || []).sort().join(',');
  const phMismatch = Object.keys(enFlat).filter(k => ph(enFlat[k]) !== ph(tFlat[k]));
  console.log(l.toUpperCase() + ' | leaf=' + Object.keys(tFlat).length + ' | missing=' + JSON.stringify(missing) + ' | extra=' + JSON.stringify(extra) + ' | phMismatch=' + JSON.stringify(phMismatch));
}
