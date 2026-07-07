#!/usr/bin/env node
/*
 * sync_tex_to_html.js — regenerate the prose sections of survey/content.html
 * from the LaTeX sources in survey/latex/ (the source of truth for prose).
 *
 * Direction: .tex  ──►  content.html   (you edit LaTeX; the website follows)
 *
 * Covered sections: intro, preliminaries, proportionality, techniques, open.
 * Figure/table-heavy sections (group-fair, individual, the results table) and
 * all figures stay hand-maintained in content.html — figures are re-inserted
 * where a "%%FIGURE:<id>" marker appears in the .tex (a LaTeX comment).
 *
 * Run by .github/workflows/sync-html.yml on every push that touches
 * survey/latex/*.tex; it opens a PR with the regenerated content.html.
 * Node stdlib only. Local run: node scripts/sync_tex_to_html.js
 */
const fs = require('fs');
const path = require('path');
const core = require('./tex2html_core.js');

const LATEX = path.join(process.cwd(), 'survey/latex');
const CONTENT = path.join(process.cwd(), 'survey/content.html');

const contentHtml = fs.readFileSync(CONTENT, 'utf8');
const refs = JSON.parse(fs.readFileSync(path.join(process.cwd(), 'survey/references.json'), 'utf8'));
let status = {};
try { status = JSON.parse(fs.readFileSync(path.join(process.cwd(), 'survey/ai_status.json'), 'utf8')); } catch (e) {}

const texByBase = {};
core.SECTIONS.forEach((sec) => {
  const plain = path.join(LATEX, sec.base + '.tex');
  const ai = path.join(LATEX, 'ai-' + sec.base + '.tex');
  const f = fs.existsSync(plain) ? plain : (fs.existsSync(ai) ? ai : null);
  if (f) texByBase[sec.base] = fs.readFileSync(f, 'utf8');
  else console.error('!! no .tex found for section "' + sec.id + '" (' + sec.base + ')');
});

const res = core.convert({ texByBase, contentHtml, refs, status });

let md = '### Sync LaTeX \u2192 HTML\n\n';
md += res.changed.length
  ? 'Regenerated section(s): **' + res.changed.join(', ') + '** in `survey/content.html`.\n\n'
  : 'No section changes.\n\n';
if (res.unknownKeys.length) {
  md += '\u26a0\ufe0f **Citation keys not in `survey/references.json`** \u2014 they will render as \u201c?\u201d on the site until an entry is added: '
      + res.unknownKeys.map((k) => '`' + k + '`').join(', ') + '\n\n';
}
if (res.warnings.length) md += 'Warnings:\n' + res.warnings.map((w) => '- ' + w).join('\n') + '\n';
fs.writeFileSync('sync_warnings.md', md);

if (res.changed.length) fs.writeFileSync(CONTENT, res.contentHtml);

const gh = process.env.GITHUB_OUTPUT;
if (gh) fs.appendFileSync(gh, 'changed=' + (res.changed.length ? 'true' : 'false') + '\nfiles=' + res.changed.join(', ') + '\n');
console.log(md);
