#!/usr/bin/env node
// Jobsearch-Kit · предотсев новых строк data/pipeline.md до оценки моделью.
// Правила — в kit-presieve.json (их собирает Claude из Rules/03_Strategy.md человека).
//   node kit-presieve.mjs           — пробный прогон, только отчёт
//   node kit-presieve.mjs --apply   — пометить отсеянные «- [x] … — presieve: причина»
// Лог: data/presieve-log.tsv. Принцип: при сомнении — пропускать вакансию дальше.
import fs from 'node:fs';

const APPLY = process.argv.includes('--apply');
const PIPE = 'data/pipeline.md';
const LOG = 'data/presieve-log.tsv';
const CFG = JSON.parse(fs.readFileSync('kit-presieve.json', 'utf8'));

const re = (p) => (p ? new RegExp(p, 'i') : null);
const titleRules = (CFG.exclude_title || []).map(r => [r.reason, re(r.pattern)]);
const companyRules = (CFG.exclude_company || []).map(r => [r.reason, re(r.pattern)]);
const protect = re(CFG.protect_company);
const globalCo = re(CFG.global_companies);
const allowedLoc = re(CFG.allowed_locations);
const maxAge = Number(CFG.max_age_days || 0);

const norm = s => (s || '').toLowerCase()
  .replace(/\(?(m|w|d|f|x|div|all genders?|gn\*?)(\s*\/\s*(m|w|d|f|x|div))*\)?/g, ' ')
  .replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

if (!fs.existsSync(PIPE)) { console.log('presieve: pipeline.md ещё нет — пропускаю'); process.exit(0); }
const lines = fs.readFileSync(PIPE, 'utf8').split('\n');
const seen = new Set();
for (const l of lines) if (l.startsWith('- [x] ')) {
  const p = l.slice(6).split(' | '); if (p.length >= 3) seen.add(norm(p[1]) + '|' + norm(p[2]));
}
const today = new Date();
const stats = {}; const log = []; let kept = 0;
for (let i = 0; i < lines.length; i++) {
  const l = lines[i]; if (!l.startsWith('- [ ] ')) continue;
  const [url = '', company = '', title = '', locRaw = ''] = l.slice(6).split(' | ');
  const loc = locRaw.replace(/posted:.*$/, '').trim();
  const posted = (l.match(/posted: (\d{4}-\d{2}-\d{2})/) || [])[1];
  let reason = null;
  if (!(protect && protect.test(company))) {
    for (const [name, rx] of companyRules) if (rx && rx.test(company)) { reason = name; break; }
    if (!reason) for (const [name, rx] of titleRules) if (rx && rx.test(title)) { reason = name; break; }
    if (!reason && globalCo && allowedLoc && globalCo.test(company) && loc) {
      let u = url; try { u = decodeURIComponent(url); } catch {}
      if (!allowedLoc.test(loc + ' ' + u)) reason = 'вне географии';
    }
    if (!reason && maxAge && posted && (today - new Date(posted)) / 864e5 > maxAge) reason = `старше ${maxAge} дней`;
    const key = norm(company) + '|' + norm(title);
    if (!reason && seen.has(key)) reason = 'дубль';
    if (!reason) seen.add(key); // отсеянная строка не делает дублем следующую (например, та же роль в другом городе)
  }
  if (reason) {
    stats[reason] = (stats[reason] || 0) + 1;
    log.push([today.toISOString().slice(0, 10), reason, company, title, loc, url].join('\t'));
    if (APPLY) lines[i] = '- [x] ' + l.slice(6) + ' — presieve: ' + reason;
  } else kept++;
}
console.log(`presieve ${today.toISOString().slice(0, 16)} ${APPLY ? 'APPLY' : 'DRY-RUN'}: отсеяно ${log.length}, осталось к оценке ${kept}`);
for (const [k, v] of Object.entries(stats).sort((a, b) => b[1] - a[1])) console.log(`  ${k}: ${v}`);
if (APPLY && log.length) {
  fs.writeFileSync(PIPE, lines.join('\n'));
  if (!fs.existsSync(LOG)) fs.writeFileSync(LOG, 'date\treason\tcompany\ttitle\tlocation\turl\n');
  fs.appendFileSync(LOG, log.join('\n') + '\n');
}
if (!APPLY) for (const r of log.slice(0, 200)) console.log('   - ' + r.split('\t').slice(1, 4).join(' | '));
