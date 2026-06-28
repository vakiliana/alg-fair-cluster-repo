#!/usr/bin/env python3
"""
edit_paper.py — apply a single manual edit to data/papers.json from inputs.

Driven by the "Edit a paper" GitHub Actions workflow (workflow_dispatch), so a
maintainer can correct a record entirely from the browser — no local git.

Inputs come from environment variables (set by the workflow form):
  FC_PAPER       paper id OR a title substring to locate the record (required)
  FC_FIELD       which field to set: citations | definition | contribution |
                 open_problems | fairness_notion | work_nature | authors |
                 venue | year | scholar_id | ai_labeled | ai_notes  (required)
  FC_VALUE       the new value (required). For list fields (open_problems,
                 work_nature) use newline- or '||'-separated items. Booleans
                 accept true/false. citations/year accept integers.

Writes data/papers.json and a Markdown summary the workflow puts in the PR body.
Stdlib only.
"""
import os
import sys

from fc_lib import load_papers, save_papers, normalize_title

LIST_FIELDS = {"open_problems", "work_nature", "tags"}
INT_FIELDS = {"citations", "year"}
BOOL_FIELDS = {"ai_labeled", "ai_notes"}
ALLOWED = LIST_FIELDS | INT_FIELDS | BOOL_FIELDS | {
    "definition", "contribution", "fairness_notion", "authors", "venue", "scholar_id", "title",
}


def find_paper(papers, key):
    key = (key or "").strip()
    for p in papers:                       # exact id first
        if p.get("id") == key:
            return p
    nk = normalize_title(key)
    matches = [p for p in papers if nk and nk in normalize_title(p.get("title", ""))]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = "\n".join(f"  - [{p['id']}] {p['title']}" for p in matches[:10])
        sys.exit(f"'{key}' matched {len(matches)} papers — be more specific:\n{names}")
    return None


def coerce(field, raw):
    if field in INT_FIELDS:
        return int(str(raw).strip())
    if field in BOOL_FIELDS:
        return str(raw).strip().lower() in ("1", "true", "yes", "y")
    if field in LIST_FIELDS:
        parts = [s.strip() for chunk in str(raw).split("||") for s in chunk.split("\n")]
        return [s for s in parts if s]
    return str(raw)


def main():
    key = os.environ.get("FC_PAPER", "").strip()
    field = os.environ.get("FC_FIELD", "").strip()
    raw = os.environ.get("FC_VALUE", "")
    if not key or not field:
        sys.exit("FC_PAPER and FC_FIELD are required.")
    if field not in ALLOWED:
        sys.exit(f"Field '{field}' is not editable. Allowed: {', '.join(sorted(ALLOWED))}")

    papers = load_papers()
    p = find_paper(papers, key)
    if not p:
        sys.exit(f"No paper found for '{key}'.")

    old = p.get(field)
    new = coerce(field, raw)
    p[field] = new

    # If a human just set notes or tags, it's no longer unverified-AI.
    import datetime
    if field in ("definition", "contribution", "open_problems"):
        p["ai_notes"] = False
    if field in ("fairness_notion", "work_nature"):
        p["ai_labeled"] = False
    if field == "citations":
        p["citations_updated"] = datetime.date.today().isoformat()

    save_papers(papers)

    def show(v):
        if isinstance(v, list):
            return "\n".join(f"    - {x}" for x in v) or "_(empty)_"
        return f"`{v}`" if v not in (None, "") else "_(empty)_"

    summary = (f"### Manual edit\n\n"
               f"**Paper:** {p['title']}  \n**id:** `{p['id']}`  \n**Field:** `{field}`\n\n"
               f"**Before:**\n{show(old)}\n\n**After:**\n{show(new)}\n")
    with open("edit_summary.md", "w", encoding="utf-8") as f:
        f.write(summary)
    print(summary)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write("changed=true\n")
        gh.write(f"title={p['title'][:60]}\n")


if __name__ == "__main__":
    main()
