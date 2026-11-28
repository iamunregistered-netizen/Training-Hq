// Dependency-free check: HTML-producing functions in public/app.js must have balanced tags.
// A single stray </div> in itemEditorHTML once pushed every exercise but the first out of the editor list.
import { readFileSync } from 'node:fs';
const src = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const FUNCS = ['itemEditorHTML', 'rampRowHTML'];
const TAGS = ['div', 'details', 'summary', 'button', 'select', 'label', 'span', 'section'];

function body(name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found`);
  const next = src.indexOf('\nfunction ', start + 10);
  return src.slice(start, next < 0 ? undefined : next);
}
// Remove ${...} expressions (including nested templates) so only the literal markup remains.
function stripExpressions(t) {
  let out = '', depth = 0;
  for (let i = 0; i < t.length; i++) {
    if (!depth && t[i] === '$' && t[i + 1] === '{') { depth = 1; i++; continue; }
    if (depth) { if (t[i] === '{') depth++; else if (t[i] === '}') depth--; continue; }
    out += t[i];
  }
  return out;
}
let failed = 0;
for (const fn of FUNCS) {
  const html = stripExpressions(body(fn));
  for (const tag of TAGS) {
    const open = (html.match(new RegExp(`<${tag}[\\s>]`, 'g')) || []).length;
    const close = (html.match(new RegExp(`</${tag}>`, 'g')) || []).length;
    if (open !== close) { failed++; console.error(`FAIL ${fn}: <${tag}> opened ${open}, closed ${close}`); }
  }
}
if (failed) { console.error(`\n${failed} unbalanced tag(s)`); process.exit(1); }
console.log(`OK — ${FUNCS.join(', ')} have balanced tags`);
