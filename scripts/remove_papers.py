#!/usr/bin/env python3
"""
remove_papers.py — remove papers from data/papers.json by id.

Driven by the "Remove papers" GitHub Action (workflow_dispatch). A maintainer
selects papers in the admin UI on the site; the site copies their ids and opens
the workflow. The workflow removes those records and opens a pull request the
maintainer can review, then accept or reject. Nothing is deleted until the PR
is merged, and only repository collaborators can run workflows.

Inputs via env:
  FC_IDS      comma / space / newline separated paper ids (required)
  FC_REASON   optional note for the PR body
"""
import json
import os
import re
import sys

from fc_lib import load_papers, save_papers


def main():
    raw = os.environ.get("FC_IDS", "")
    reason = os.environ.get("FC_REASON", "").strip()
    ids = [x for x in re.split(r"[\s,]+", raw.strip()) if x]
    if not ids:
        sys.exit("FC_IDS is required (comma/space/newline separated paper ids).")

    papers = load_papers()
    by_id = {p.get("id"): p for p in papers}

    removed, missing = [], []
    for i in ids:
        if i in by_id:
            removed.append(by_id[i])
        else:
            missing.append(i)

    if not removed:
        print("No matching papers found. Nothing to do.")
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
            gh.write("changed=false\n")
        return

    remove_ids = {p.get("id") for p in removed}
    kept = [p for p in papers if p.get("id") not in remove_ids]
    save_papers(kept)

    # Record removed papers in the blacklist so discovery never re-adds them.
    from fc_lib import load_blacklist, save_blacklist, normalize_title
    import datetime
    bl = load_blacklist()
    entries = list(bl["raw"])
    have = {(e.get("id") or normalize_title(e.get("title", ""))) for e in entries}
    today = datetime.date.today().isoformat()
    for p in removed:
        key = p.get("id") or normalize_title(p.get("title", ""))
        if key in have:
            continue
        entries.append({"id": p.get("id", ""), "title": p.get("title", ""),
                        "removed": today, "reason": reason})
        have.add(key)
    save_blacklist(entries)

    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write("changed=true\n")
        gh.write(f"count={len(removed)}\n")

    with open("removal_summary.md", "w", encoding="utf-8") as f:
        f.write(f"### Proposed removal of {len(removed)} paper(s)\n\n")
        if reason:
            f.write(f"**Reason:** {reason}\n\n")
        f.write("Review the list below. **Merge** this PR to remove them, or **close** it to keep them. "
                "Removed papers are added to `data/blacklist.json` so the discovery bot will not re-add them automatically.\n\n")
        f.write("| id | title | venue | year | citations |\n|---|---|---|---:|---:|\n")
        for p in removed:
            title = (p.get("title", "") or "").replace("|", "\\|")
            f.write(f"| `{p.get('id','')}` | {title[:90]} | {p.get('venue','')} | {p.get('year','') or ''} | {p.get('citations',0)} |\n")
        if missing:
            f.write(f"\n_Note: {len(missing)} id(s) not found and skipped: "
                    + ", ".join(f"`{m}`" for m in missing) + "._\n")

    print(f"Removed {len(removed)} paper(s); {len(missing)} id(s) not found.")


if __name__ == "__main__":
    main()
