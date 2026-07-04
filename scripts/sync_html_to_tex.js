#!/usr/bin/env node
/*
 * sync_html_to_tex.js — regenerate the prose LaTeX section files from the
 * survey's web source (survey/content.html), which is the single source of
 * truth. Run by the "Sync LaTeX from HTML" workflow whenever content.html
 * changes; it opens a PR with the regenerated .tex so you review before merge.
 *
 * What it does:
 *   - splits content.html into sections by <h2 id> / <h3 id>
 *   - converts the prose of each section to LaTeX (headings, emphasis, code,
 *     lists, inline $math$, citations <span class="cite" data-k="k1,k2"> -> \citep{})
 *   - writes ONLY the mapped prose files listed in SECTION_FILES below
 *   - never touches figures, tables, the preamble, or the bibliography — those
 *     stay hand-maintained in LaTeX (figures are SVG-only on the web).
 *
 * Node stdlib only (no npm). Usage: node scripts/sync_html_to_tex.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = process.cwd();
const CONTENT = path.join(ROOT, 'survey/content.html');
const LATEX_DIR = path.join(ROOT, 'survey/latex');

// Which section ids are regenerated, and into which .tex file + \section title.
// Figure/table-heavy or author-owned sections are intentionally omitted so the
// converter never clobbers hand-authored LaTeX (intro, group-fair, individual,
// the results table, and all figures remain manual).
const SECTIONS = [
  { id: 'preliminaries',    file: 'ai-preliminaries.tex',  title: 'Preliminaries and Notation', label: 'sec:prelim', ai: true },
  { id: 'proportionality',  file: 'ai-proportionality.tex',title: 'Proportionality, the Core, and Stability', label: 'sec:prop', ai: true },
  { id: 'techniques',       file: 'ai-techniques.tex',     title: 'Algorithmic Techniques', label: 'sec:tech', ai: true },
  { id: 'future-directions',file: 'ai-open.tex',           title: 'Future Directions and Open Problems', label: 'sec:open', ai: true },
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

// Convert one run of inline HTML (already isolated from block tags) to LaTeX.
function inlineToTex(html) {
  let out = '';
  let i = 0;
  while (i < html.length) {
    // preserve inline math $...$ verbatim
    if (html[i] === '$') {
      let j = i + 1; while (j < html.length && html[j] !== '$') j++;
      out += html.slice(i, j + 1); i = j + 1; continue;
    }
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
          // skip to closing </span>
          const close = html.indexOf('</span>', i);
          i = (close >= 0 ? close + 7 : i + m[0].length); continue;
        }
        else if (tag === 'span' && /class="nokatex"/.test(attrs)) {
          // the resource $ badge etc. -> literal
          const inner = html.slice(i + m[0].length, html.indexOf('</span>', i));
          out += '\\$'; i = html.indexOf('</span>', i) + 7; continue;
        }
        i += m[0].length; continue;
      }
      if (cm) {
        const tag = cm[1].toLowerCase();
        if (['em','i','strong','b','code'].includes(tag)) out += '}';
        i += cm[0].length; continue;
      }
    }
    // plain char
    let j = i; while (j < html.length && html[j] !== '<' && html[j] !== '$') j++;
    out += decode(html.slice(i, j)); i = j;
  }
  return out.replace(/[ \t]+/g, ' ').trim();
}

function blockToTex(block) {
  block = block.trim();
  if (!block) return '';
  let m;
  if ((m = block.match(/^<h3[^>]*>([\s\S]*?)<\/h3>$/i)))
    return '\\subsection{' + inlineToTex(m[1]) + '}';
  if ((m = block.match(/^<h4[^>]*>([\s\S]*?)<\/h4>$/i)))
    return '\\subsubsection{' + inlineToTex(m[1]) + '}';
  if (/^<p class="runin">/.test(block)) {
    const inner = block.replace(/^<p[^>]*>/, '').replace(/<\/p>$/, '');
    // run-in bold lead -> \paragraph
    const pm = inner.match(/^<strong>([\s\S]*?)<\/strong>\s*([\s\S]*)$/);
    if (pm) return '\\paragraph{' + inlineToTex(pm[1]) + '} ' + inlineToTex(pm[2]);
    return inlineToTex(inner);
  }
  if ((m = block.match(/^<p[^>]*>([\s\S]*?)<\/p>$/i)))
    return inlineToTex(m[1]);
  if (/^<ul/.test(block)) {
    const items = [...block.matchAll(/<li[^>]*>([\s\S]*?)<\/li>/gi)].map(x => '  \\item ' + inlineToTex(x[1]));
    return '\\begin{itemize}[leftmargin=1.2em]\n' + items.join('\n') + '\n\\end{itemize}';
  }
  return ''; // figures, tables, banners, etc. are skipped
}

function extractSection(html, id) {
  // grab from the section heading to the next <h2 or end
  const re = new RegExp('<h2[^>]*id="' + id + '"[^>]*>[\\s\\S]*?(?=<h2|<section class="refs"|$)', 'i');
  const m = html.match(re);
  return m ? m[0] : null;
}

function main() {
  const html = fs.readFileSync(CONTENT, 'utf8');
  let changed = [];
  for (const sec of SECTIONS) {
    const chunk = extractSection(html, sec.id);
    if (!chunk) { console.error('!! section not found: ' + sec.id); continue; }
    // drop the leading <h2>…</h2> and any ai-banner div; keep the rest as blocks
    let body = chunk.replace(/^<h2[\s\S]*?<\/h2>/i, '')
                    .replace(/<div class="ai-banner"[\s\S]*?<\/div>/gi, '');
    // split into top-level blocks
    const blocks = body.match(/<(h3|h4|p|ul)[\s\S]*?<\/\1>/gi) || [];
    const texBody = blocks.map(blockToTex).filter(Boolean).join('\n\n');
    const header = (sec.ai ? '% ===== AI-DRAFTED (pending author review) =====\n' : '')
      + '% Auto-generated from survey/content.html by scripts/sync_html_to_tex.js — do not edit by hand.\n'
      + '\\section{' + sec.title + '}\\label{' + sec.label + '}\n'
      + (sec.ai ? '\\aibanner\n' : '') + '\n';
    const outPath = path.join(LATEX_DIR, sec.file);
    const next = header + texBody + '\n';
    const prev = fs.existsSync(outPath) ? fs.readFileSync(outPath, 'utf8') : '';
    if (next !== prev) { fs.writeFileSync(outPath, next); changed.push(sec.file); }
  }
  const ghOut = process.env.GITHUB_OUTPUT;
  if (ghOut) fs.appendFileSync(ghOut, 'changed=' + (changed.length ? 'true' : 'false') + '\n'
    + 'files=' + changed.join(', ') + '\n');
  console.log(changed.length ? 'Regenerated: ' + changed.join(', ') : 'No LaTeX changes.');
}

main();
