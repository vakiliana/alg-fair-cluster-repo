#!/usr/bin/env python3
"""
survey_review.py — mark AI-drafted survey sections as author-reviewed and
SCRUB every AI-generated label for them.

For each reviewed section this removes:
  * the "AI-drafted" banner + gold tag on the website (survey/content.html:
    the ai-section class and the ai-banner block),
  * the "% ===== AI-DRAFTED =====" comment and the \\aibanner line in the
    matching LaTeX source, RENAMING ai-<name>.tex -> <name>.tex and fixing
    the \\input in fair_clustering_survey.tex,
  * its entry in the provenance box (the LaTeX box is regenerated between the
    PROV-AI-START/END markers; the web box rebuilds itself from ai_status.json).

Driven by the "Survey — mark AI section reviewed" workflow, which opens a
pull request for the maintainer to merge (accept) or close (reject).
Un-reviewing (reviewed=false) restores only the status flag and provenance
lists — scrubbed banners/comments/filenames come back only via git history.
"""
import json
import os
import re
import sys

STATUS = "survey/ai_status.json"
CONTENT = "survey/content.html"
MAIN_TEX = "survey/latex/fair_clustering_survey.tex"

SECTIONS = {
    "abstract":          dict(html_id=None, tex=None, prov="Abstract"),
    "preliminaries":     dict(html_id="preliminaries", tex=("ai-preliminaries", "preliminaries"),
                              prov=r"Preliminaries \& Notation (\S\ref{sec:prelim})"),
    "proportionality":   dict(html_id="proportionality", tex=("ai-proportionality", "proportionality"),
                              prov=r"Proportionality/Core \& Stability (\S\ref{sec:prop})"),
    "techniques":        dict(html_id="techniques", tex=("ai-techniques", "techniques"),
                              prov=r"Algorithmic Techniques (\S\ref{sec:tech})"),
    "future-directions": dict(html_id="future-directions", tex=("ai-open", "open"),
                              prov=r"Future Directions (\S\ref{sec:open})"),
    "fig-taxonomy":      dict(html_id=None, tex=None, prov="the taxonomy figure"),
    "tab-results":       dict(html_id=None, tex=("ai-results-table", "results-table"),
                              prov=r"Table~\ref{tab:results}"),
}
AUTHOR_BASE = ["Introduction", "Group-Fairness Notions", "Individual Fairness", "Conclusion"]


def scrub_html(html_id):
    if not html_id or not os.path.exists(CONTENT):
        return False
    with open(CONTENT, encoding="utf-8") as f:
        c = f.read()
    c2 = re.sub(rf'(<h2 id="{html_id}") class="ai-section"', r"\1", c)
    c2 = re.sub(rf'(<h2 id="{html_id}"[^>]*>.*?</h2>)\s*<div class="ai-banner">.*?</div>',
                r"\1", c2, flags=re.S)
    if c2 != c:
        with open(CONTENT, "w", encoding="utf-8") as f:
            f.write(c2)
        return True
    return False


def scrub_tex(pair):
    if not pair:
        return []
    old, new = pair
    changes = []
    src, dst = f"survey/latex/{old}.tex", f"survey/latex/{new}.tex"
    path = src if os.path.exists(src) else (dst if os.path.exists(dst) else None)
    if path:
        with open(path, encoding="utf-8") as f:
            t = f.read()
        t2 = "\n".join(l for l in t.split("\n")
                       if not l.strip().startswith("% ===== AI-DRAFTED")
                       and l.strip() != r"\aibanner")
        t2 = t2.replace(r" \emph{AI-drafted table; verify before use.}", "")
        with open(dst, "w", encoding="utf-8") as f:
            f.write(t2)
        if path == src and src != dst:
            os.remove(src)
            changes.append(f"renamed `{old}.tex` → `{new}.tex`")
        changes.append(f"scrubbed AI labels in `{new}.tex`")
    else:
        changes.append(f"⚠️ `{old}.tex` not found in repo — LaTeX scrub skipped (push survey/latex first)")
    if os.path.exists(MAIN_TEX):
        with open(MAIN_TEX, encoding="utf-8") as f:
            m = f.read()
        m2 = m.replace("\\input{%s}" % old, "\\input{%s}" % new)
        if m2 != m:
            with open(MAIN_TEX, "w", encoding="utf-8") as f:
                f.write(m2)
            changes.append("updated \\input in fair_clustering_survey.tex")
    return changes


def regen_provenance(status):
    if not os.path.exists(MAIN_TEX):
        return False
    with open(MAIN_TEX, encoding="utf-8") as f:
        m = f.read()
    if "% PROV-AI-START" not in m:
        return False
    authors, pending = AUTHOR_BASE[:], []
    for k, meta in SECTIONS.items():
        (authors if status.get(k) else pending).append(meta["prov"])
    lines = [r"\textbf{Author-written or author-reviewed:} " + ", ".join(authors) + "."]
    if pending:
        lines.append(r"\textbf{AI-drafted (pending review):} " + ", ".join(pending)
                     + ". AI-drafted sections also carry an inline banner.")
    else:
        lines.append(r"\textbf{All AI-drafted material has been reviewed and approved by the author.}")
    block = "% PROV-AI-START\n" + "\n".join(lines) + "\n% PROV-AI-END"
    m2 = re.sub(r"% PROV-AI-START.*?% PROV-AI-END", lambda _: block, m, flags=re.S)
    if m2 != m:
        with open(MAIN_TEX, "w", encoding="utf-8") as f:
            f.write(m2)
        return True
    return False


def main():
    section = os.environ.get("FC_SECTION", "").strip()
    reviewed = os.environ.get("FC_REVIEWED", "true").strip().lower() in ("1", "true", "yes")
    if not section:
        sys.exit("FC_SECTION is required.")
    keys = list(SECTIONS) if section == "all" else [section]
    for k in keys:
        if k not in SECTIONS:
            sys.exit(f"Unknown section '{k}'. Valid: {', '.join(SECTIONS)}, all")

    with open(STATUS, encoding="utf-8") as f:
        status = json.load(f)

    notes = []
    for k in keys:
        if status.get(k) != reviewed:
            status[k] = reviewed
            notes.append(f"`{k}`: status → {'reviewed' if reviewed else 'pending'}")
        if reviewed:
            if scrub_html(SECTIONS[k]["html_id"]):
                notes.append(f"`{k}`: removed web AI banner + tag")
            notes += [f"`{k}`: {c}" for c in scrub_tex(SECTIONS[k]["tex"])]
        else:
            notes.append(f"`{k}`: un-reviewed (scrubbed labels return only via git revert)")

    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)
        f.write("\n")
    if regen_provenance(status):
        notes.append("regenerated LaTeX provenance box")

    verb = "author-reviewed" if reviewed else "pending review"
    with open("review_summary.md", "w", encoding="utf-8") as f:
        f.write(f"### Mark {section} as {verb}\n\n")
        f.write("This PR scrubs the AI-drafted labels for the reviewed section(s): web banner/tag, "
                "LaTeX `% AI-DRAFTED` comments and `\\aibanner`, `ai-*.tex` filenames, and the provenance box. "
                "**Merge** to publish, **close** to reject.\n\n")
        f.write("\n".join(f"- {n}" for n in notes) or "- (no changes)")
        f.write("\n")
    print("\n".join(notes) or "(no changes)")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if notes else 'false'}\n")


if __name__ == "__main__":
    main()
