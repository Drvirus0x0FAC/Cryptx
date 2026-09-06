// Static audit: find React inline styles with hardcoded DARK colors that would
// show as dark-on-light in light mode (CSS var usage is fine; hardcoded hex/rgb is the risk).
import fs from 'node:fs';
import path from 'node:path';

const root = 'C:/Users/drvir/OneDrive/Desktop/CryptoOSINT-Production/frontend/src';
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.tsx') || e.name.endsWith('.ts')) files.push(p);
  }
})(root);

// A color is "dark" if its luminance is low. Parse hex (#rgb/#rrggbb) and rgb().
function isDark(color) {
  let r, g, b;
  const hex = color.match(/^#([0-9a-f]{3,8})$/i);
  if (hex) {
    let h = hex[1];
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    r = parseInt(h.slice(0, 2), 16); g = parseInt(h.slice(2, 4), 16); b = parseInt(h.slice(4, 6), 16);
  } else {
    const m = color.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (!m) return false;
    [, r, g, b] = m.map(Number);
  }
  return (r + g + b) / 3 < 60; // avg < 60 = dark
}

const findings = [];
for (const f of files) {
  const lines = fs.readFileSync(f, 'utf8').split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Match style={{ background: '#xxx' }} or backgroundColor: '#xxx' or color: '#xxx'
    const matches = [...line.matchAll(/(background(?:Color)?|backgroundColor|borderColor|color)\s*:\s*['"](#?[0-9a-fA-F]{3,8}|rgba?\([^)]+\))['"]/g)];
    for (const m of matches) {
      const prop = m[1];
      const val = m[2];
      // Only flag backgrounds/borders (text color dark on light bg is usually fine/correct)
      if (!/background|border/i.test(prop)) continue;
      if (isDark(val)) {
        const rel = f.replace(/\\/g, '/').split('/src/')[1];
        findings.push({ file: rel, line: i + 1, prop, val, ctx: line.trim().slice(0, 90) });
      }
    }
  }
}

// Group by file
const byFile = {};
for (const f of findings) (byFile[f.file] ??= []).push(f);
console.log(`Dark hardcoded background/border colors in inline styles: ${findings.length} across ${Object.keys(byFile).length} files\n`);
for (const [file, items] of Object.entries(byFile).sort((a, b) => b[1].length - a[1].length)) {
  console.log(`\n▼ ${file} (${items.length})`);
  for (const it of items) console.log(`  L${it.line}  ${it.prop}: ${it.val}  | ${it.ctx}`);
}
fs.writeFileSync('C:/Users/drvir/OneDrive/Desktop/CryptoOSINT-Production/UI_INLINE_DARK_AUDIT.json', JSON.stringify(findings, null, 2));
