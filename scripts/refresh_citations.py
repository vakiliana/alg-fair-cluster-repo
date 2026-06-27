#!/usr/bin/env python3
"""
refresh_citations.py — robust, cautious Google Scholar citation refresh via SerpApi.

Design goals (after an author-batch attempt produced wrong matches):

  * ACCURACY FIRST. Each paper is looked up with a Google Scholar *search*
    (engine=google_scholar). Among the returned results we keep only those whose
    title matches the paper (exact-normalized or high token overlap) and take the
    one with the HIGHEST citation count — i.e. Scholar's canonical merged entry,
    not a low-cited preprint duplicate.

  * SANITY GUARD. Citation counts essentially never fall and never jump by orders
    of magnitude month-to-month. Any proposed change that DROPS the count (beyond
    a tiny tolerance) or SPIKES it implausibly is treated as a likely mismatch:
    it is NOT written, and is surfaced in the PR under "Needs manual check".
    This alone catches every bad value from the previous run (301→41, 66→2851, …).

  * CAUTIOUS API USE. A staleness gate skips papers refreshed within
    FC_MIN_AGE_DAYS; papers are processed oldest-first; and FC_MAX_QUERIES hard-
    caps SerpApi calls per run, so a large corpus refreshes gradually. Cluster ids
    are cached per paper in `scholar_id` for exact, cheap re-lookups.

Env (all optional except the key):
  SERPAPI_KEY        required — https://serpapi.com/manage-api-key
  FC_MIN_AGE_DAYS    skip papers refreshed more recently than this (default 25)
  FC_MAX_QUERIES     hard cap on SerpApi calls this run (default 200)
  FC_SLEEP           seconds between calls (default 1.2)
  FC_FORCE           "1" to ignore the staleness gate
  FC_DECREASE_TOL    allowed downward wobble before flagging (default 2)
  FC_SPIKE_FACTOR    flag if new > old * this and old is non-trivial (default 4)
  FC_SPIKE_ABS       ...and the absolute jump exceeds this (default 150)

Stdlib only.  Local run:  SERPAPI_KEY=xxx python scripts/refresh_citations.py
"""
import datetime
import os
import sys
import time
import json
import urllib.parse
import urllib.request

from fc_lib import load_papers, save_papers, normalize_title

API_KEY = os.environ.get("SERPAPI_KEY", "").strip()
ENDPOINT = "https://serpapi.com/search.json"

MIN_AGE_DAYS = int(os.environ.get("FC_MIN_AGE_DAYS", "25"))
MAX_QUERIES = int(os.environ.get("FC_MAX_QUERIES", "200"))
SLEEP = float(os.environ.get("FC_SLEEP", "1.2"))
FORCE = os.environ.get("FC_FORCE", "") == "1"
DECREASE_TOL = int(os.environ.get("FC_DECREASE_TOL", "2"))
SPIKE_FACTOR = float(os.environ.get("FC_SPIKE_FACTOR", "4"))
SPIKE_ABS = int(os.environ.get("FC_SPIKE_ABS", "150"))

_calls = 0


def serp_get(params):
    global _calls
    _calls += 1
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "fair-clustering-repo-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def cited_by(result):
    cb = ((result.get("inline_links") or {}).get("cited_by") or {})
    v = cb.get("total")
    return v if isinstance(v, int) else None


def cluster_id(result):
    cb = ((result.get("inline_links") or {}).get("cited_by") or {})
    return cb.get("cluster_id") or ""


def result_authors(result):
    pi = result.get("publication_info") or {}
    names = [a.get("name", "") for a in (pi.get("authors") or []) if a.get("name")]
    if names:
        return " ".join(names)
    return (pi.get("summary") or "").split(" - ")[0]   # fallback: text before the venue


def surnames(s):
    return {t for t in normalize_title(s).split() if len(t) > 2}   # drop initials


def author_overlap(result, paper):
    rs, ps = surnames(result_authors(result)), surnames(paper.get("authors", ""))
    return len(rs & ps) if rs and ps else 0


def tokens(title):
    return set(normalize_title(title).split())


def title_match(a, b):
    """Exact normalized match, or high token overlap (handles LaTeX-stripped
    titles like 'individually fair -clustering' vs '… k-clustering')."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    jac = len(ta & tb) / len(ta | tb)
    return jac >= 0.82


def best_count(paper):
    """Return (count, cluster_id, matched) for a paper. One SerpApi call.
    Among title-matching results, prefers the one whose AUTHORS overlap this
    paper's authors, then the highest citation count (Scholar's merged entry).
    Author verification stops a wrong same-titled paper from being matched."""
    if paper.get("scholar_id"):
        data = serp_get({"engine": "google_scholar", "cluster": paper["scholar_id"], "api_key": API_KEY})
        res = data.get("organic_results") or []
        counts = [cited_by(r) for r in res if cited_by(r) is not None]
        return (max(counts) if counts else None), paper["scholar_id"], bool(res)

    data = serp_get({"engine": "google_scholar", "q": paper["title"], "num": "10", "api_key": API_KEY})
    res = data.get("organic_results") or []
    cands = [r for r in res if title_match(r.get("title", ""), paper["title"])]
    if not cands:
        return None, "", False
    # If any candidate's authors match ours, restrict to those (kills same-title
    # different-paper mismatches like the old 301->41); else fall back to all.
    verified = [r for r in cands if author_overlap(r, paper) > 0]
    pool = verified or cands
    best = max(pool, key=lambda r: (author_overlap(r, paper), cited_by(r) or -1))
    cid = cluster_id(best) or best.get("result_id", "")
    return cited_by(best), cid, True


def classify(old, new):
    """'apply' | 'drop' | 'spike' — the sanity guard."""
    if new is None:
        return "none"
    if new < old - DECREASE_TOL:
        return "drop"
    if old >= 10 and new > old * SPIKE_FACTOR and (new - old) > SPIKE_ABS:
        return "spike"
    return "apply"


def main():
    if not API_KEY:
        print("ERROR: SERPAPI_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    papers = load_papers()
    today = datetime.date.today().isoformat()
    cutoff = datetime.date.today() - datetime.timedelta(days=MIN_AGE_DAYS)

    def is_stale(p):
        if FORCE or not p.get("citations_updated"):
            return True
        try:
            return datetime.date.fromisoformat(p["citations_updated"]) < cutoff
        except Exception:
            return True

    stale = [p for p in papers if p.get("title") and is_stale(p)]
    stale.sort(key=lambda p: p.get("citations_updated") or "")
    print(f"{len(stale)} of {len(papers)} papers stale (> {MIN_AGE_DAYS}d). Budget {MAX_QUERIES} calls.")

    applied, flagged, unmatched = [], [], []
    for p in stale:
        if _calls >= MAX_QUERIES:
            print(f"Budget reached ({MAX_QUERIES}); remaining papers left for next run.")
            break
        old = p.get("citations", 0) or 0
        try:
            new, cid, matched = best_count(p)
        except Exception as e:
            print(f"  ! {p['title'][:60]}: {e}", file=sys.stderr)
            time.sleep(SLEEP)
            continue

        if not matched:
            unmatched.append(p["title"])
            p["citations_updated"] = today          # stamp so we don't re-hit it constantly
            time.sleep(SLEEP)
            continue
        if cid and not p.get("scholar_id"):
            p["scholar_id"] = cid

        verdict = classify(old, new)
        if verdict == "apply":
            p["citations_updated"] = today
            if new != old:
                p["citations"] = new
                applied.append((p["title"], old, new))
                print(f"  {old:>5} -> {new:<5}  {p['title'][:60]}")
        elif verdict in ("drop", "spike"):
            # Likely a mismatch — DO NOT write. Surface for manual review.
            flagged.append((p["title"], old, new, verdict))
            print(f"  FLAG ({verdict}) {old} -> {new}  {p['title'][:55]}")
        time.sleep(SLEEP)

    save_papers(papers)
    print(f"\nApplied {len(applied)}, flagged {len(flagged)}, unmatched {len(unmatched)}. "
          f"SerpApi calls: {_calls}/{MAX_QUERIES}.")

    changed = len(applied) > 0 or len(flagged) > 0
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if len(applied) else 'false'}\n")
        gh.write(f"count={len(applied)}\n")
        gh.write(f"flagged={len(flagged)}\n")
        gh.write(f"calls={_calls}\n")

    if changed:
        with open("citation_summary.md", "w", encoding="utf-8") as f:
            f.write(f"### Google Scholar citation refresh — {today}\n\n")
            f.write(f"Applied **{len(applied)}** update(s) using **{_calls}** SerpApi call(s) "
                    f"(stale-gated at {MIN_AGE_DAYS}d, budget {MAX_QUERIES}).\n\n")
            if applied:
                applied.sort(key=lambda d: d[2] - d[1], reverse=True)
                f.write("| Δ | was | now | paper |\n|---:|---:|---:|---|\n")
                for t, o, n in applied[:100]:
                    f.write(f"| {n - o:+d} | {o} | {n} | {t[:80]} |\n")
            if flagged:
                f.write(f"\n### ⚠️ Needs manual check — NOT applied ({len(flagged)})\n\n")
                f.write("These proposed changes look like Scholar mismatches (a drop, or an "
                        "implausible spike) and were left untouched. Verify by hand; if real, "
                        "edit the count in `data/papers.json` (or fix the paper's `scholar_id`).\n\n")
                f.write("| was | proposed | why | paper |\n|---:|---:|:--|---|\n")
                for t, o, n, why in flagged:
                    f.write(f"| {o} | {n} | {why} | {t[:80]} |\n")
            if unmatched:
                f.write(f"\n_{len(unmatched)} paper(s) had no confident title match this run "
                        f"(left unchanged)._\n")


if __name__ == "__main__":
    main()
