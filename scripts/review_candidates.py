#!/usr/bin/env python3
"""
review_candidates.py — apply the admin's Accept/Reject decisions to papers
with status "pending-review" (scraped by discovery or submitted by users).

Driven by the "Review candidates (admin)" workflow, dispatched from the
site's admin Review modal (or manually from the Actions tab).

  Accept  -> status cleared (paper goes live) + appended to
             survey/new_papers_queue.json (the "update the survey" feed)
  Reject  -> removed from data/papers.json + added to data/blacklist.json
             (never auto-suggested again; manual user submissions still
             surface it to the admin, flagged)

Env:
  FC_ACCEPT       ids to accept (comma/space separated)
  FC_REJECT       ids to reject
  FC_CLEAR_QUEUE  "true" to empty survey/new_papers_queue.json (after the
                  survey has been updated with those papers)
  FC_QUEUE_REMOVE ids to drop from the update-survey queue (exclude specific
                  accepted papers from the next survey update)
"""
import datetime
import json
import os
import re

from fc_lib import load_papers, save_papers, load_blacklist, save_blacklist, normalize_title

QUEUE = "survey/new_papers_queue.json"


def ids_from(v):
    return [x for x in re.split(r"[\s,]+", (v or "").strip()) if x]


def main():
    accept = ids_from(os.environ.get("FC_ACCEPT"))
    reject = ids_from(os.environ.get("FC_REJECT"))
    clear_q = os.environ.get("FC_CLEAR_QUEUE", "").strip().lower() in ("1", "true", "yes")
    queue_remove = set(ids_from(os.environ.get("FC_QUEUE_REMOVE")))

    papers = load_papers()
    by_id = {p.get("id"): p for p in papers}
    today = datetime.date.today().isoformat()
    try:
        with open(QUEUE, encoding="utf-8") as f:
            queue = json.load(f)
        if not isinstance(queue, list):
            queue = []
    except Exception:
        queue = []

    accepted, rejected, missing = [], [], []

    for i in accept:
        p = by_id.get(i)
        if not p:
            missing.append(i)
            continue
        p["status"] = ""
        p.pop("was_blacklisted", None)
        accepted.append(p)
        # append to the update-survey queue (skip if this id is already queued)
        if not any((q.get("id") == p.get("id")) for q in queue):
            queue.append({"id": p.get("id", ""), "title": p.get("title", ""),
                          "link": p.get("link") or p.get("pdf") or "", "added": today})

    bl = load_blacklist()
    entries = list(bl["raw"])
    have = {(e.get("id") or normalize_title(e.get("title", ""))) for e in entries}
    rej_ids = set()
    for i in reject:
        p = by_id.get(i)
        if not p:
            missing.append(i)
            continue
        rej_ids.add(i)
        rejected.append(p)
        key = p.get("id") or normalize_title(p.get("title", ""))
        if key not in have:
            entries.append({"id": p.get("id", ""), "title": p.get("title", ""),
                            "removed": today, "reason": "rejected in admin review"})
            have.add(key)

    papers = [p for p in papers if p.get("id") not in rej_ids]
    removed_from_queue = [q for q in queue if q.get("id") in queue_remove]
    if queue_remove:
        queue = [q for q in queue if q.get("id") not in queue_remove]
    if clear_q:
        queue = []

    changed = bool(accepted or rejected or clear_q or removed_from_queue)
    if changed:
        save_papers(papers)
        save_blacklist(entries)
        with open(QUEUE, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
            f.write("\n")
        with open("review_summary.md", "w", encoding="utf-8") as f:
            f.write("### Admin review decisions\n\n")
            f.write("**Merge** this PR to finalize the decisions below; **close** it to discard them. "
                    "Undecided papers were not touched and remain in the review queue.\n\n")
            if accepted:
                f.write(f"**Accepted \u2192 published ({len(accepted)}):**\n\n| id | title |\n|---|---|\n")
                for p in accepted:
                    f.write(f"| `{p.get('id','')}` | {(p.get('title','') or '').replace('|', '\\|')[:90]} |\n")
                f.write("\n")
            if rejected:
                f.write(f"**Rejected \u2192 removed + blacklisted ({len(rejected)}):**\n\n| id | title |\n|---|---|\n")
                for p in rejected:
                    f.write(f"| `{p.get('id','')}` | {(p.get('title','') or '').replace('|', '\\|')[:90]} |\n")
                f.write("\n")
            if clear_q:
                f.write("**Update-survey queue cleared.**\n\n")
            if removed_from_queue:
                f.write(f"**Excluded from the survey update ({len(removed_from_queue)}):**\n\n")
                for q in removed_from_queue:
                    f.write(f"- {(q.get('title','') or q.get('id','')).replace('|', '\\|')[:90]}\n")
                f.write("\n")
            if missing:
                f.write("_Ids not found (skipped): " + ", ".join(f"`{m}`" for m in missing) + "._\n")

    summary = f"accept {len(accepted)}, reject {len(rejected)}" + (", queue cleared" if clear_q else "") + (f", {len(removed_from_queue)} excluded from survey" if removed_from_queue else "")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if changed else 'false'}\n")
        gh.write(f"summary={summary}\n")
    print("Accepted:", [p.get("id") for p in accepted])
    print("Rejected:", [p.get("id") for p in rejected])
    if missing:
        print("Ids not found (skipped):", missing)


if __name__ == "__main__":
    main()
