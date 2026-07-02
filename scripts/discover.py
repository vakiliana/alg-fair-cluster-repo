#!/usr/bin/env python3
"""
discover.py — monthly discovery of new fair-clustering papers.

Scans arXiv + DBLP for candidate papers, filters to genuine fair-clustering
work, removes anything already in data/papers.json, auto-tags the survivors
with heuristic fairness-notion / work-nature labels, and APPENDS them to
data/papers.json with status="pending-review".

The GitHub Actions workflow then opens a pull request. The PR diff is your
approval queue: review each new entry, fix its tags, optionally write the
Definition / Contribution / Open-problems notes, delete anything off-topic,
then merge. Merging to main publishes it (status can be cleared or left).

No third-party packages — urllib + xml/json from the stdlib only.
Run locally with:  python scripts/discover.py
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from fc_lib import (
    load_papers, save_papers, existing_title_index, normalize_title,
    new_record, is_fair_clustering, load_blacklist, find_near_duplicate,
)

UA = {"User-Agent": "fair-clustering-repo-bot/1.0 (+https://github.com/vakiliana/alg-fair-cluster-repo)"}

# Search queries — broad enough to catch new work, the relevance gate trims noise.
ARXIV_QUERIES = [
    'all:"fair clustering"',
    'all:"fairness" AND all:"clustering"',
    'all:"socially fair" AND all:"clustering"',
    'all:"individual fairness" AND all:"clustering"',
]
DBLP_QUERIES = ["fair clustering", "fairness clustering", "socially fair clustering"]

ARXIV_MAX = 60
DBLP_MAX = 60


def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------
# arXiv  (Atom API)
# --------------------------------------------------------------------------
def search_arxiv():
    out = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for q in ARXIV_QUERIES:
        url = ("http://export.arxiv.org/api/query?search_query="
               + urllib.parse.quote(q)
               + f"&start=0&max_results={ARXIV_MAX}&sortBy=submittedDate&sortOrder=descending")
        try:
            xml = fetch(url)
        except Exception as e:
            print(f"  arXiv query failed ({q}): {e}", file=sys.stderr)
            continue
        root = ET.fromstring(xml)
        for e in root.findall("a:entry", ns):
            title = " ".join((e.find("a:title", ns).text or "").split())
            summary = " ".join((e.find("a:summary", ns).text or "").split())
            if not is_fair_clustering(title, summary):
                continue
            arxiv_url = e.find("a:id", ns).text or ""
            arxiv_id = arxiv_url.rstrip("/").split("/")[-1]
            pdf = ""
            for link in e.findall("a:link", ns):
                if link.get("title") == "pdf":
                    pdf = link.get("href", "")
            authors = ", ".join((a.find("a:name", ns).text or "") for a in e.findall("a:author", ns))
            published = e.find("a:published", ns)
            year = int(published.text[:4]) if published is not None and published.text else None
            out.append(dict(id=arxiv_id, title=title, authors=authors, year=year,
                            venue="arXiv", link=arxiv_url, pdf=pdf, bib_link=""))
        time.sleep(3)  # be polite to arXiv
    return out


# --------------------------------------------------------------------------
# DBLP  (JSON API)
# --------------------------------------------------------------------------
def search_dblp():
    out = []
    for q in DBLP_QUERIES:
        url = ("https://dblp.org/search/publ/api?q="
               + urllib.parse.quote(q) + f"&format=json&h={DBLP_MAX}")
        try:
            data = json.loads(fetch(url))
        except Exception as e:
            print(f"  DBLP query failed ({q}): {e}", file=sys.stderr)
            continue
        hits = (((data or {}).get("result") or {}).get("hits") or {}).get("hit") or []
        for h in hits:
            info = h.get("info", {})
            title = " ".join((info.get("title") or "").rstrip(".").split())
            if not is_fair_clustering(title):
                continue
            authors_field = (info.get("authors") or {}).get("author") or []
            if isinstance(authors_field, dict):
                authors_field = [authors_field]
            authors = ", ".join(a.get("text", "") if isinstance(a, dict) else str(a) for a in authors_field)
            year = int(info["year"]) if info.get("year", "").isdigit() else None
            key = info.get("key", "")          # e.g. conf/nips/Foo24
            short = key.split("/")[-1] if key else normalize_title(title)[:32]
            bib_link = f"https://dblp.org/rec/{key}" if key else ""
            out.append(dict(id=short, title=title, authors=authors, year=year,
                            venue=info.get("venue", ""), link=info.get("ee", ""),
                            pdf="", bib_link=bib_link))
        time.sleep(2)
    return out


def main():
    papers = load_papers()
    seen = existing_title_index(papers)
    blacklist = load_blacklist()
    today = datetime.date.today().isoformat()

    candidates = search_arxiv() + search_dblp()
    print(f"Fetched {len(candidates)} raw candidates from arXiv + DBLP.")

    added, blocked, dup_flagged = [], [], []
    local_seen = set(seen.keys())
    for c in candidates:
        nt = normalize_title(c["title"])
        if not nt or nt in local_seen:
            continue
        # Skip anything an admin previously removed (blacklist).
        if c.get("id") in blacklist["ids"] or nt in blacklist["titles"]:
            blocked.append(c["title"])
            continue
        local_seen.add(nt)
        # Near-duplicate check against the existing database.
        dup, sim = find_near_duplicate(c["title"], papers, threshold=0.8)
        dup_of = ""
        if dup and sim < 1.0:
            dup_of = f"{dup.get('id','')} — {dup.get('title','')}"
            dup_flagged.append((c["title"], dup.get("title", ""), sim))
        rec = new_record(c["title"], id=c["id"], authors=c["authors"], year=c["year"],
                         venue=c["venue"], link=c["link"], pdf=c["pdf"],
                         bib_link=c["bib_link"], added=today, status="pending-review",
                         possible_duplicate_of=dup_of)
        # Keep gscholar-style ids unique across the database.
        existing_ids = {p.get("id") for p in papers}
        if rec["id"] in existing_ids:
            for suf in "abcdefgh":
                if rec["id"] + suf not in existing_ids:
                    rec["id"] += suf
                    break
        papers.append(rec)
        added.append(rec)

    if blocked:
        print(f"Skipped {len(blocked)} blacklisted (previously-removed) candidate(s).")

    if not added:
        print("No new fair-clustering papers found. Nothing to do.")
        # Signal "no changes" to the workflow.
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
            gh.write("changed=false\n")
        return


    save_papers(papers)
    print(f"Added {len(added)} candidate(s):")
    lines = [f"- **{r['title']}** ({r['venue'] or '?'} {r['year'] or ''}) — "
             f"`{r['fairness_notion']}`" for r in added]
    print("\n".join(lines))

    # Hand a Markdown summary + change flag to the workflow for the PR body.
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write("changed=true\n")
        gh.write(f"count={len(added)}\n")
    with open("discovery_summary.md", "w", encoding="utf-8") as f:
        f.write(f"### {len(added)} new fair-clustering candidate(s)\n\n")
        f.write("Review each entry below, refine its **fairness notion** / **work nature** tags, "
                "optionally add Definition / Contribution / Open-problems notes, delete anything "
                "off-topic, then merge.\n\n")
        f.write("\n".join(lines) + "\n")
        if dup_flagged:
            f.write(f"\n### ⚠️ Possible duplicates ({len(dup_flagged)})\n\n")
            f.write("These candidates closely match a paper already in the database. Check before "
                    "merging — delete the block if it's the same paper (each carries a "
                    "`possible_duplicate_of` field).\n\n")
            f.write("| similarity | candidate | existing paper |\n|---:|---|---|\n")
            for cand, exist, sim in dup_flagged:
                f.write(f"| {int(sim*100)}% | {cand[:70]} | {exist[:70]} |\n")
        if blocked:
            f.write(f"\n_Skipped {len(blocked)} previously-removed (blacklisted) candidate(s)._\n")


if __name__ == "__main__":
    main()
