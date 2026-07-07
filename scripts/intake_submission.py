#!/usr/bin/env python3
"""
intake_submission.py — turn a "[paper] …" GitHub issue (created by the site's
"Submit a missing paper" form) into a pending-review record in
data/papers.json, so it appears in the admin's in-site Review queue alongside
papers found by the discovery bot.

Blacklisted titles are still queued (a manual submission may surface a
previously-rejected paper), but flagged so the admin sees the history.

Env (set by .github/workflows/intake-submission.yml):
  ISSUE_TITLE, ISSUE_BODY, ISSUE_NUMBER, GITHUB_TOKEN, GITHUB_REPOSITORY
"""
import datetime
import json
import os
import re
import urllib.request

from fc_lib import load_papers, save_papers, normalize_title, new_record, load_blacklist, find_near_duplicate


def gh_comment(msg):
    tok = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    num = os.environ.get("ISSUE_NUMBER", "")
    if not (tok and repo and num):
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{num}/comments",
        data=json.dumps({"body": msg}).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                 "User-Agent": "fair-clustering-bot"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print("comment failed:", e)


def field(body, name):
    m = re.search(r"\*\*" + re.escape(name) + r":\*\*\s*(.+)", body)
    return m.group(1).strip() if m else ""


def main():
    body = os.environ.get("ISSUE_BODY", "") or ""
    ititle = os.environ.get("ISSUE_TITLE", "") or ""
    num = os.environ.get("ISSUE_NUMBER", "")
    out = open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a")

    title = field(body, "Title") or re.sub(r"^\[paper\]\s*", "", ititle).strip()
    link = field(body, "Paper link")
    bib = field(body, "DBLP/BibTeX")
    if bib == "(none)":
        bib = ""
    if not title:
        gh_comment("\u26a0\ufe0f Could not parse a title from this submission; a maintainer will handle it manually.")
        out.write("changed=false\n")
        return

    papers = load_papers()
    nt = normalize_title(title)
    if any(normalize_title(p.get("title", "")) == nt for p in papers):
        gh_comment("This paper appears to already be in the repository (or its review queue), so it was not queued again. A maintainer will double-check.")
        out.write("changed=false\n")
        return

    bl = load_blacklist()
    was_bl = nt in bl["titles"]
    dup, _sim = find_near_duplicate(title, papers, threshold=0.8)

    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]+\.[0-9]+)", link or "")
    pid = m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", nt)[:40].strip("-")
    if any(p.get("id") == pid for p in papers):
        pid = f"{pid}-s{num or 1}"

    rec = new_record(title, id=pid, link=link, bib_link=bib,
                     added=datetime.date.today().isoformat(), status="pending-review",
                     possible_duplicate_of=(f"{dup.get('id','')} \u2014 {dup.get('title','')}" if dup else ""))
    rec["submitted_via"] = f"issue #{num}"
    if was_bl:
        rec["was_blacklisted"] = True
    papers.append(rec)
    save_papers(papers)

    note = f"\u2705 Queued for admin review on the site (record id `{pid}`)."
    if was_bl:
        note += "\n\n\u26a0\ufe0f A paper with this title was previously rejected/removed by an admin; it is being shown to the admin again because this is a manual submission."
    if dup:
        note += f"\n\n\u26a0\ufe0f Possible duplicate of existing entry: {dup.get('title','')}"
    gh_comment(note)
    out.write("changed=true\n")
    print("Queued:", pid, "-", title)


if __name__ == "__main__":
    main()
