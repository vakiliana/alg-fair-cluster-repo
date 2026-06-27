#!/usr/bin/env python3
"""
refresh_citations.py — monthly Google Scholar citation refresh via SerpApi.

For every paper in data/papers.json it asks SerpApi's Google Scholar engine
for the current cited-by count and writes it back, along with the Scholar
cluster id (cached in `scholar_id` so future runs are exact and cheaper) and
a `citations_updated` date stamp.

Requires the SERPAPI_KEY secret (https://serpapi.com/manage-api-key).
The GitHub Actions workflow opens a pull request with the citation deltas so
you can eyeball them before publishing; set OPEN_PR=false in the workflow to
commit straight to main instead.

Stdlib only.  Local run:  SERPAPI_KEY=xxx python scripts/refresh_citations.py
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from fc_lib import load_papers, save_papers

API_KEY = os.environ.get("SERPAPI_KEY", "").strip()
ENDPOINT = "https://serpapi.com/search.json"
SLEEP = float(os.environ.get("FC_SERP_SLEEP", "1.2"))   # politeness between calls
# Optional cap for testing; 0 = no limit.
LIMIT = int(os.environ.get("FC_LIMIT", "0"))


def serp_get(params):
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "fair-clustering-repo-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def lookup_by_cluster(cluster_id):
    """Exact lookup once we know the Scholar cluster id."""
    data = serp_get({"engine": "google_scholar", "cluster": cluster_id, "api_key": API_KEY})
    res = (data.get("organic_results") or [])
    if not res:
        return None, cluster_id
    return _extract(res[0]), cluster_id


def lookup_by_title(title):
    """First-time lookup by title; returns (count, cluster_id)."""
    data = serp_get({"engine": "google_scholar", "q": title, "num": "5", "api_key": API_KEY})
    res = (data.get("organic_results") or [])
    if not res:
        return None, ""
    # Prefer an exact-ish title match, else take the top hit.
    target = title.lower().strip()
    best = res[0]
    for r in res:
        if (r.get("title", "").lower().strip()[:60]) == target[:60]:
            best = r
            break
    return _extract(best), best.get("result_id", "")


def _extract(result):
    cb = ((result.get("inline_links") or {}).get("cited_by") or {})
    return cb.get("total", None)


def main():
    if not API_KEY:
        print("ERROR: SERPAPI_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    papers = load_papers()
    today = datetime.date.today().isoformat()
    changed = 0
    deltas = []
    processed = 0

    for p in papers:
        if LIMIT and processed >= LIMIT:
            break
        title = p.get("title", "")
        if not title:
            continue
        processed += 1
        old = p.get("citations", 0) or 0
        try:
            if p.get("scholar_id"):
                count, cid = lookup_by_cluster(p["scholar_id"])
            else:
                count, cid = lookup_by_title(title)
                if cid:
                    p["scholar_id"] = cid
        except Exception as e:
            print(f"  ! {title[:60]}: {e}", file=sys.stderr)
            time.sleep(SLEEP)
            continue

        p["citations_updated"] = today
        if count is not None and count != old:
            p["citations"] = count
            changed += 1
            deltas.append((title, old, count))
            print(f"  {old:>5} -> {count:<5}  {title[:64]}")
        time.sleep(SLEEP)

    save_papers(papers)
    print(f"\nUpdated {changed} citation count(s) across {processed} paper(s).")

    # Workflow signalling + PR summary.
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if changed else 'false'}\n")
        gh.write(f"count={changed}\n")
    if changed:
        deltas.sort(key=lambda d: abs(d[2] - d[1]), reverse=True)
        with open("citation_summary.md", "w", encoding="utf-8") as f:
            f.write(f"### Google Scholar citation refresh — {today}\n\n")
            f.write(f"Updated **{changed}** of {processed} papers.\n\n")
            f.write("| Δ | was | now | paper |\n|---:|---:|---:|---|\n")
            for title, o, n in deltas[:80]:
                f.write(f"| {n - o:+d} | {o} | {n} | {title[:80]} |\n")


if __name__ == "__main__":
    main()
