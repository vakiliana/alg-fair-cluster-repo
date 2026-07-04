#!/usr/bin/env node
/*
 * sync_html_to_tex.js — regenerate the prose LaTeX section files from the
 * survey's web source (survey/content.html), the single source of truth.
 * Run by the "Sync LaTeX from HTML" workflow whenever content.html changes;
 * it opens a PR with the regenerated .tex so you review before merge.
 *
 * Covers every FIGURE-FREE prose section (intro + the four originally-AI
 * sections). Figure/table-heavy sections (group-fair, individual, the results
 * table) stay hand-maintained in LaTeX and are never touched, because their
 * figures/tables live only in LaTeX.
 *
 * Filename awareness: a section that has been marked reviewed in
 * survey/ai_status.json is written WITHOUT the "ai-" prefix (matching the
 * rename that scripts/survey_review.py performs) and WITHOUT the AI banner /
 * comment. A pending AI section keeps the ai- prefix, banner, and comment.
 *
 * Node stdlib only. Usage: node scripts/sync_html_to_tex.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = process.cwd();
const CONTENT = path.join(ROOT, 'survey/content.html');
const LATEX_DIR = path.join(ROOT, 'survey/latex');
const STATUS = path.join(ROOT, 'survey/ai_status.json');

let status = {};
try { status = JSON.parse(fs.readFileSync(STATUS, 'utf8')); } catch (e) { status = {}; }

// id  -> section spec. `ai` marks originally-AI sections (banner + ai- prefix
// until reviewed). `base` is the filename stem; reviewed AI sections drop ai-.
const SECTIONS = [
  { id: 'introduction',      base: 'intro',           title: 'Introduction', label: 'sec:intro', ai: false },
  { id: 'preliminaries',     base: 'preliminaries',   title: 'Preliminaries and Notation', label: 'sec:prelim', ai: true, statusKey: 'preliminaries' },
  { id: 'proportionality',   base: 'proportionality', title: 'Proportionality, the Core, and Stability', label: 'sec:prop', ai: true, statusKey: 'proportionality' },
  { id: 'techniques',        base: 'techniques',      title: 'Algorithmic Techniques', label: 'sec:tech', ai: true, statusKey: 'techniques' },
  { id: 'future-directions', base: 'open',            title: 'Future Directions and Open Problems', label: 'sec:open', ai: true, statusKey: 'future-directions' },
];

function decode(s) {
  return s.replace(/&nbsp;/g, '~').replace(/&thinsp;/g, '\\,')
          .replace(/&amp;/g, '\\&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
          .replace(/&#36;/g, '\\$').replace(/&middot;/g, '\\textperiodcentered ')
          .replace(/\u2013/g, '--').replace(/\u2014/g, '---')
          .replace(/\u2018/g, '`').replace(/\u2019/g, "'")
          .replace(/\u201c/g, '``').replace(/\u201d/g, "''")
          .replace(/\u2026/g, '\\ldots ');
}

function inlineToTex(html) {
  // strip superscript AI marks / any <sup>…</sup> (web-only annotations)
  html = html.replace(/<sup[^>]*>[\s\S]*?<\/sup>/gi, '');
  let out = '', i = 0;
  while (i < html.length) {
    if (html[i] === '$') { let j = i + 1; while (j < html.length && html[j] !== '$') j++; out += html.slice(i, j + 1); i = j + 1; continue; }
    if (html[i] === '<') {
      const m = html.slice(i).match(/^<([a-zA-Z0-9]+)([^>]*)>/);
      const cm = html.slice(i).match(/^<\/([a-zA-Z0-9]+)>/);
      if (m) {
        const tag = m[1].toLowerCase(), attrs = m[2];
        if (tag === 'em' || tag === 'i') out += '\\emph{';
        else if (tag === 'strong' || tag === 'b') out += '\\textbf{';
        else if (tag === 'code') out += '\\texttt{';
        else if (tag === 'span' && /class="cite"/.test(attrs)) {
          const k = (attrs.match(/data-k="([^"]*)"/) || [, ''])[1];
          out += '\\citep{' + k + '}';
          const close = html.indexOf('</span>', i);
          i = (close >= 0 ? close + 7 : i + m[0].length); continue;
        }
        else if (tag === 'span' && /class="nokatex"/.test(attrs)) {
          out += '\\$'; const close = html.indexOf('</span>', i);
          i = (close >= 0 ? close + 7 : i + m[0].length); continue;
        }
        i += m[0].length; continue;
      }
      if (cm) {
        const tag = cm[1].toLowerCase();
        if (['em', 'i', 'strong', 'b', 'code'].includes(tag)) out += '}';
        i += cm[0].length; continue;
      }
    }
    let j = i; while (j < html.length && html[j] !== '<' && html[j] !== '$') j++;
    out += decode(html.slice(i, j)); i = j;
  }
  return out.replace(/[ \t]+/g, ' ').trim();
}

function blockToTex(block) {
  block = block.trim(); if (!block) return '';
  let m;
  if ((m = block.match(/^<h3[^>]*>([\s\S]*?)<\/h3>$/i))) return '\\subsection{' + inlineToTex(m[1]) + '}';
  if ((m = block.match(/^<h4[^>]*>([\s\S]*?)<\/h4>$/i))) return '\\subsubsection{' + inlineToTex(m[1]) + '}';
  if (/^<p class="runin">/.test(block)) {
    const inner = block.replace(/^<p[^>]*>/, '').replace(/<\/p>$/, '');
    const pm = inner.match(/^<strong>([\s\S]*?)<\/strong>\s*([\s\S]*)$/);
    if (pm) return '\\paragraph{' + inlineToTex(pm[1]) + '} ' + inlineToTex(pm[2]);
    return inlineToTex(inner);
  }
  if ((m = block.match(/^<p[^>]*>([\s\S]*?)<\/p>$/i))) return inlineToTex(m[1]);
  if (/^<ul/.test(block)) {
    const items = [...block.matchAll(/<li[^>]*>([\s\S]*?)<\/li>/gi)].map(x => '  \\item ' + inlineToTex(x[1]));
    return '\\begin{itemize}[leftmargin=1.2em]\n' + items.join('\n') + '\n\\end{itemize}';
  }
  return '';
}

function extractSection(html, id) {
  const re = new RegExp('<h2[^>]*id="' + id + '"[^>]*>[\\s\\S]*?(?=<h2|<section class="refs"|$)', 'i');
  const m = html.match(re);
  return m ? m[0] : null;
}

function main() {
  const html = fs.readFileSync(CONTENT, 'utf8');
  const changed = [];
  for (const sec of SECTIONS) {
    const chunk = extractSection(html, sec.id);
    if (!chunk) { console.error('!! section not found: ' + sec.id); continue; }
    let body = chunk.replace(/^<h2[\s\S]*?<\/h2>/i, '')
                    .replace(/<div class="ai-banner"[\s\S]*?<\/div>/gi, '')
                    .replace(/<figure[\s\S]*?<\/figure>/gi, '')
                    .replace(/<div class="table-wrap"[\s\S]*?<\/div>\s*<\/div>/gi, '');
    const blocks = body.match(/<(h3|h4|p|ul)[\s\S]*?<\/\1>/gi) || [];
    const texBody = blocks.map(blockToTex).filter(Boolean).join('\n\n');

    const reviewed = sec.ai && sec.statusKey ? !!status[sec.statusKey] : false;
    const isAI = sec.ai && !reviewed;                 // still AI-labelled?
    const stem = isAI ? 'ai-' + sec.base : sec.base;  // filename honours review state
    const header =
      (isAI ? '% ===== AI-DRAFTED (pending author review) =====\n' : '') +
      '% Auto-generated from survey/content.html by scripts/sync_html_to_tex.js — do not edit by hand.\n' +
      '\\section{' + sec.title + '}\\label{' + sec.label + '}\n' +
      (isAI ? '\\aibanner\n' : '') + '\n';
    const outPath = path.join(LATEX_DIR, stem + '.tex');
    const next = header + texBody + '\n';
    const prev = fs.existsSync(outPath) ? fs.readFileSync(outPath, 'utf8') : '';
    if (next !== prev) { fs.writeFileSync(outPath, next); changed.push(stem + '.tex'); }
    // if reviewed, make sure the stale ai- file isn't left behind
    if (!isAI && sec.ai) {
      const stale = path.join(LATEX_DIR, 'ai-' + sec.base + '.tex');
      if (fs.existsSync(stale)) { fs.unlinkSync(stale); changed.push('removed ai-' + sec.base + '.tex'); }
    }
  }
  const ghOut = process.env.GITHUB_OUTPUT;
  if (ghOut) fs.appendFileSync(ghOut, 'changed=' + (changed.length ? 'true' : 'false') + '\nfiles=' + changed.join(', ') + '\n');
  console.log(changed.length ? 'Regenerated: ' + changed.join(', ') : 'No LaTeX changes.');
}

main();
