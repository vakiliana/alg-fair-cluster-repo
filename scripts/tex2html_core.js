/*
 * tex2html_core.js — pure LaTeX→HTML converter for the survey's prose sections.
 * survey/latex/*.tex is the source of truth; this regenerates the matching
 * sections inside survey/content.html. Used by scripts/sync_tex_to_html.js
 * (Node, in CI) and testable in a browser (UMD).
 *
 * Supported TeX subset (what the prose sections use):
 *   \section/\subsection/\subsubsection/\paragraph, \emph/\textit, \textbf,
 *   \texttt, \textsc, {\bf ...}/{\it ...}/{\sc ...}, \citep/\cite/\citet,
 *   \footnote, \textcolor, \ref (via a label map), itemize/enumerate,
 *   $inline math$ (passed to KaTeX; < > escaped), ~, ---, --, ``quotes'',
 *   \ldots, \& \% \_ \# \$, %%FIGURE:<html-id> markers (re-insert the web
 *   figure stored in content.html at that spot).
 */
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory();
  else root.Tex2Html = factory();
})(typeof self !== 'undefined' ? self : this, function () {

  var SECTIONS = [
    { id: 'introduction',      base: 'intro',           ai: false, statusKey: null },
    { id: 'preliminaries',     base: 'preliminaries',   ai: true,  statusKey: 'preliminaries' },
    { id: 'proportionality',   base: 'proportionality', ai: true,  statusKey: 'proportionality' },
    { id: 'techniques',        base: 'techniques',      ai: true,  statusKey: 'techniques' },
    { id: 'future-directions', base: 'open',            ai: true,  statusKey: 'future-directions' },
  ];

  var LABELMAP = {
    'fig:bal_rep_clustering': '<a href="#fig-balance">Figure&nbsp;2</a>',
    'fig:taxonomy': '<a href="#fig-taxonomy">Figure&nbsp;1</a>',
    'tab:results': '<a href="#results-summary">Table&nbsp;1</a>',
    'sec:prelim': '<a href="#preliminaries">Preliminaries</a>',
    'sec:group-fairness': '<a href="#group-fairness-notions-in-clustering">the group-fairness section</a>',
    'sec:prop': '<a href="#proportionality">the proportionality section</a>',
    'sec:tech': '<a href="#techniques">the techniques section</a>',
    'sec:open': '<a href="#future-directions">the open-problems section</a>',
  };

  var AI_BANNER_FALLBACK = '<div class="ai-banner"><svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><path d="M12 2l1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2z"/></svg><span><strong>AI-drafted section</strong> \u2014 synthesized by Claude from the cited literature, <strong>pending author review</strong>. Please verify claims and constants before relying on them.</span></div>';

  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function stripTags(s) { return s.replace(/<[^>]+>/g, ''); }
  function normTitle(s) { return stripTags(s).toLowerCase().replace(/\$[^$]*\$/g, ' ').replace(/[^a-z0-9]+/g, ' ').trim(); }
  function slug(s) { return normTitle(s).replace(/\s+/g, '-').slice(0, 50).replace(/^-+|-+$/g, ''); }

  function extractBraced(s, openIdx) {
    var depth = 0, k = openIdx;
    do { if (s[k] === '{') depth++; else if (s[k] === '}') depth--; k++; } while (k < s.length && depth > 0);
    return { arg: s.slice(openIdx + 1, k - 1), end: k };
  }

  function inlineToHtml(s, ctx) {
    var out = '', i = 0, n = s.length;
    while (i < n) {
      var ch = s[i];
      if (ch === '$') {
        var j = i + 1; while (j < n && s[j] !== '$') j++;
        out += '$' + esc(s.slice(i + 1, j)) + '$'; i = j + 1; continue;
      }
      if (ch === '\\') {
        var two = s.substr(i, 2);
        if (two === '\\&') { out += '&amp;'; i += 2; continue; }
        if (two === '\\%') { out += '%'; i += 2; continue; }
        if (two === '\\_') { out += '_'; i += 2; continue; }
        if (two === '\\#') { out += '#'; i += 2; continue; }
        if (two === '\\$') { out += '<span class="nokatex">$</span>'; i += 2; continue; }
        if (two === '\\,') { out += '&thinsp;'; i += 2; continue; }
        if (two === '\\ ') { out += ' '; i += 2; continue; }
        if (two === '\\\\') { out += '<br>'; i += 2; continue; }
        var m = /^\\([a-zA-Z]+)\*?/.exec(s.slice(i));
        if (!m) { i++; continue; }
        var cmd = m[1]; i += m[0].length;
        if (s[i] === '[') { var rb = s.indexOf(']', i); if (rb >= 0) i = rb + 1; }
        var grab = function () { if (s[i] !== '{') return null; var e = extractBraced(s, i); i = e.end; return e.arg; };
        if (cmd === 'ldots' || cmd === 'dots') { out += '\u2026'; continue; }
        if (cmd === 'aibanner' || cmd === 'centering' || cmd === 'noindent' || cmd === 'smallskip' || cmd === 'medskip' || cmd === 'bigskip' || cmd === 'item') { continue; }
        if (cmd === 'label') { grab(); continue; }
        if (cmd === 'emph' || cmd === 'textit') { out += '<em>' + inlineToHtml(grab() || '', ctx) + '</em>'; continue; }
        if (cmd === 'textbf') { out += '<strong>' + inlineToHtml(grab() || '', ctx) + '</strong>'; continue; }
        if (cmd === 'texttt') { out += '<code>' + inlineToHtml(grab() || '', ctx) + '</code>'; continue; }
        if (cmd === 'textsc') { out += '<span class="sc">' + inlineToHtml(grab() || '', ctx) + '</span>'; continue; }
        if (cmd === 'textcolor') { grab(); out += inlineToHtml(grab() || '', ctx); continue; }
        if (cmd === 'footnote') {
          var note = stripTags(inlineToHtml(grab() || '', ctx)).replace(/"/g, '&quot;');
          out += '<sup class="fn" data-note="' + note + '">\u2020</sup>'; continue;
        }
        if (cmd === 'citep' || cmd === 'cite' || cmd === 'citealp' || cmd === 'citealt' || cmd === 'citet') {
          var keys = (grab() || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean);
          keys.forEach(function (k) { ctx.usedKeys[k] = 1; });
          var span = '<span class="cite" data-k="' + keys.join(',') + '"></span>';
          out += (cmd === 'citet') ? ctx.citetText(keys[0]) + '&nbsp;' + span : span;
          continue;
        }
        if (cmd === 'ref' || cmd === 'Cref' || cmd === 'cref' || cmd === 'autoref' || cmd === 'eqref') {
          var lab = grab() || '';
          if (LABELMAP[lab]) out += LABELMAP[lab];
          else { ctx.warnings.push('Unmapped \\ref{' + lab + '} \u2014 emitted plain text'); out += esc(lab); }
          continue;
        }
        var arg = grab();
        if (arg !== null) { ctx.warnings.push('Unknown \\' + cmd + '{\u2026} \u2014 kept contents'); out += inlineToHtml(arg, ctx); }
        else ctx.warnings.push('Unknown \\' + cmd + ' \u2014 dropped');
        continue;
      }
      if (ch === '{') {
        var gm = /^\{\\(bf|it|em|sc|tt)\s+/.exec(s.slice(i));
        if (gm) {
          var e2 = extractBraced(s, i);
          var conv = inlineToHtml(s.slice(i + gm[0].length, e2.end - 1), ctx);
          if (gm[1] === 'bf') out += '<strong>' + conv + '</strong>';
          else if (gm[1] === 'sc') out += '<span class="sc">' + conv + '</span>';
          else if (gm[1] === 'tt') out += '<code>' + conv + '</code>';
          else out += '<em>' + conv + '</em>';
          i = e2.end; continue;
        }
        i++; continue;
      }
      if (ch === '}') { i++; continue; }
      if (ch === '~') { out += '&nbsp;'; i++; continue; }
      if (s.substr(i, 3) === '---') { out += '\u2014'; i += 3; continue; }
      if (s.substr(i, 2) === '--') { out += '\u2013'; i += 2; continue; }
      if (s.substr(i, 2) === '``') { out += '\u201c'; i += 2; continue; }
      if (s.substr(i, 2) === "''") { out += '\u201d'; i += 2; continue; }
      if (ch === '`') { out += '\u2018'; i++; continue; }
      var j2 = i;
      while (j2 < n && '\\${}~`\'-'.indexOf(s[j2]) < 0) j2++;
      if (j2 === i) { out += (ch === '-' || ch === "'") ? ch : esc(ch); i++; continue; }
      out += esc(s.slice(i, j2)); i = j2;
    }
    return out;
  }

  // Parse one section's .tex source into typed blocks.
  function texToBlocks(src, ctx) {
    var lines = src.split(/\r?\n/);
    var blocks = [], buf = null, env = null, envLines = [];
    var sectionTitle = null;
    function flush() { if (buf && buf.lines.join(' ').trim()) blocks.push(buf); buf = null; }
    for (var li = 0; li < lines.length; li++) {
      var raw = lines[li];
      var fm = /^\s*%%FIGURE:(\S+)/.exec(raw);
      if (fm) { flush(); blocks.push({ type: 'figure', id: fm[1] }); continue; }
      // strip unescaped-% comments
      var line = '', escp = false;
      for (var c = 0; c < raw.length; c++) {
        var chch = raw[c];
        if (chch === '%' && !escp) break;
        line += chch; escp = (chch === '\\' && !escp);
      }
      var t = line.trim();
      if (env) {
        if (new RegExp('^\\\\end\\{' + env + '\\}').test(t)) {
          var items = envLines.join('\n').split(/\\item\s+/).map(function (x) { return x.trim(); }).filter(Boolean);
          blocks.push({ type: 'list', items: items }); env = null; envLines = [];
        } else envLines.push(t);
        continue;
      }
      if (!t) { flush(); continue; }
      var bm = /^\\begin\{(itemize|enumerate)\}/.exec(t);
      if (bm) { flush(); env = bm[1]; envLines = []; continue; }
      if (/^\\section/.test(t)) {
        var e = extractBraced(t, t.indexOf('{'));
        sectionTitle = e.arg;
        var rest = t.slice(e.end).replace(/\\label\{[^}]*\}/g, '').trim();
        if (rest) { buf = { type: 'para', lines: [rest] }; }
        continue;
      }
      if (/^\\aibanner\b/.test(t)) { var r2 = t.replace(/^\\aibanner\b/, '').trim(); if (r2) { flush(); buf = { type: 'para', lines: [r2] }; } continue; }
      var hm = /^\\(subsection|subsubsection)\*?\{/.exec(t);
      if (hm) {
        flush();
        var eh = extractBraced(t, t.indexOf('{'));
        blocks.push({ type: hm[1] === 'subsection' ? 'h3' : 'h4', title: eh.arg });
        var rest2 = t.slice(eh.end).replace(/\\label\{[^}]*\}/g, '').trim();
        if (rest2) buf = { type: 'para', lines: [rest2] };
        continue;
      }
      var pm = /^\\paragraph\*?\{/.exec(t);
      if (pm) {
        flush();
        var ep = extractBraced(t, t.indexOf('{'));
        buf = { type: 'runin', lead: ep.arg, lines: [t.slice(ep.end).trim()] };
        continue;
      }
      if (!buf) buf = { type: 'para', lines: [] };
      buf.lines.push(t);
    }
    flush();
    return { title: sectionTitle, blocks: blocks };
  }

  function renderBlocks(blocks, ctx) {
    return blocks.map(function (b) {
      if (b.type === 'figure') {
        var fig = ctx.figures[b.id];
        if (!fig) { ctx.warnings.push('Figure not found in content.html: ' + b.id); return ''; }
        ctx.placedFigures[b.id] = 1;
        return fig;
      }
      if (b.type === 'h3' || b.type === 'h4') {
        var txt = inlineToHtml(b.title, ctx);
        var id = ctx.idFor(b.title);
        return '<' + b.type + (id ? ' id="' + id + '"' : '') + '>' + txt + '</' + b.type + '>';
      }
      if (b.type === 'runin') {
        return '<p class="runin"><strong>' + inlineToHtml(b.lead, ctx) + '</strong> ' + inlineToHtml(b.lines.join(' '), ctx) + '</p>';
      }
      if (b.type === 'list') {
        var items = b.items.map(function (it) { return '<li>' + inlineToHtml(it.replace(/\s*\n\s*/g, ' '), ctx) + '</li>'; }).join('\n');
        return '<ul class="open-list">\n' + items + '\n</ul>';
      }
      return '<p>' + inlineToHtml(b.lines.join(' '), ctx) + '</p>';
    }).filter(Boolean).join('\n');
  }

  function convert(opts) {
    var contentHtml = opts.contentHtml;
    var refs = opts.refs || { refs: [], keyToNum: {} };
    var status = opts.status || {};
    var texByBase = opts.texByBase || {};
    var warnings = [], usedKeys = {}, changed = [];

    var authorsByKey = {};
    (refs.refs || []).forEach(function (r) { authorsByKey[r.key] = r.authors || []; });
    function surname(nm) { var t = nm.trim().split(/\s+/); return t[t.length - 1]; }
    function citetText(key) {
      var a = authorsByKey[key];
      if (!a || !a.length) { warnings.push('\\citet on unknown key ' + key + ' \u2014 used generic text'); return 'the authors of'; }
      if (a.length === 1) return surname(a[0]);
      if (a.length === 2) return surname(a[0]) + ' and ' + surname(a[1]);
      return surname(a[0]) + ' et al.';
    }

    // figure library + banner template from the current content.html
    var figures = {};
    (contentHtml.match(/<figure id="[^"]+"[\s\S]*?<\/figure>/g) || []).forEach(function (f) {
      figures[(f.match(/<figure id="([^"]+)"/) || [])[1]] = f;
    });
    var bannerM = contentHtml.match(/<div class="ai-banner">[\s\S]*?<\/span><\/div>/);
    var banner = bannerM ? bannerM[0] : AI_BANNER_FALLBACK;

    SECTIONS.forEach(function (sec) {
      var src = texByBase[sec.base];
      if (!src) return;
      // locate the existing section chunk
      var re = new RegExp('<h2[^>]*id="' + sec.id + '"[\\s\\S]*?(?=<h2\\b|$)');
      var oldM = contentHtml.match(re);
      if (!oldM) { warnings.push('Section not found in content.html: ' + sec.id + ' \u2014 skipped'); return; }
      var oldChunk = oldM[0];

      // heading-id reuse map from the old chunk
      var idByTitle = {};
      (oldChunk.match(/<h([34]) id="[^"]+"[^>]*>[\s\S]*?<\/h\1>/g) || []).forEach(function (h) {
        var idm = h.match(/id="([^"]+)"/); var tm = h.replace(/<[^>]+>/g, '');
        if (idm) idByTitle[normTitle(tm)] = idm[1];
      });

      var ctx = {
        usedKeys: usedKeys, warnings: warnings, figures: figures, placedFigures: {},
        citetText: citetText,
        idFor: function (title) {
          var plain = normTitle(inlineToHtml(title, { usedKeys: {}, warnings: [], figures: {}, placedFigures: {}, citetText: citetText, idFor: function () { return ''; } }));
          return idByTitle[plain] || slug(title);
        },
      };

      var parsed = texToBlocks(src, ctx);
      var isAI = sec.ai && !(status[sec.statusKey]);
      var titleHtml = inlineToHtml(parsed.title || sec.id, ctx);
      var body = renderBlocks(parsed.blocks, ctx);

      // keep any figures that were in the old chunk but have no marker yet
      (oldChunk.match(/<figure id="([^"]+)"/g) || []).map(function (x) { return x.match(/"([^"]+)"/)[1]; })
        .forEach(function (fid) {
          if (!ctx.placedFigures[fid] && figures[fid]) {
            body += '\n' + figures[fid];
            warnings.push('Figure ' + fid + ' had no %%FIGURE marker in ' + sec.base + '.tex \u2014 appended at section end');
          }
        });

      var html = '<h2 id="' + sec.id + '"' + (isAI ? ' class="ai-section"' : '') + '>' + titleHtml + '</h2>\n'
        + (isAI ? banner + '\n' : '') + body + '\n';

      if (html.trim() !== oldChunk.trim()) {
        contentHtml = contentHtml.replace(oldChunk, html);
        changed.push(sec.id);
      }
    });

    var unknownKeys = Object.keys(usedKeys).filter(function (k) { return !(refs.keyToNum || {})[k]; });
    return { contentHtml: contentHtml, changed: changed, warnings: warnings, unknownKeys: unknownKeys };
  }

  return { SECTIONS: SECTIONS, convert: convert };
});
