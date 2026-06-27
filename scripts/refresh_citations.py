#!/usr/bin/env python3
"""
refresh_citations.py — responsible, low-volume Google Scholar citation refresh via SerpApi.

SerpApi's Google Scholar *search* returns one paper per query, so there is no way
to fetch 100 distinct papers' citations in a single call. To use the API
cautiously this script does two things:

  1. AUTHOR-BATCH PASS (the real saver). SerpApi's `google_scholar_author`
     endpoint returns up to 100 of ONE author's papers — each with its cited-by
     count — in a single call. Fair-clustering papers cluster around a small set
     of prolific authors, so a handful of author calls updates most of the
     corpus. Articles are matched to our papers by *exact normalized title*, so a
     wrong author profile simply produces no matches (it can't corrupt data).

  2. BUDGETED, STALENESS-GATED FALLBACK. Anything still missing is looked up
     per-title (or by cached Scholar cluster id). Papers refreshed within
     FC_MIN_AGE_DAYS are skipped, the rest are processed oldest-first, and a hard
     per-run cap (FC_MAX_QUERIES) bounds total SerpApi calls — so even a large
     corpus is refreshed gradually across runs instead of in one burst.

Env (all optional except the key):
  SERPAPI_KEY        required — https://serpapi.com/manage-api-key
  FC_MIN_AGE_DAYS    skip papers refreshed more recently than this (default 25)
  FC_MAX_QUERIES     hard cap on SerpApi calls this run (default 130)
  FC_BATCH           "1" to use the author-batch pass (default "1")
  FC_RESOLVE_AUTHORS "1" to auto-resolve unknown author ids (default "1")
  FC_AUTHOR_PAGES    pages of 100 articles per author (default 2)
  FC_MIN_AUTHOR_PAPERS only batch authors with >= this many corpus papers (default 2)
  FC_SLEEP           seconds between calls (default 1.2)
  FC_FORCE           "1" to ignore the staleness gate

Author ids resolved once are cached in data/scholar_authors.json so we never
re-resolve them. Cluster ids are cached per paper in `scholar_id`. Stdlib only.

Local run:  SERPAPI_KEY=xxx python scripts/refresh_citations.py
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from fc_lib import load_papers, save_papers, normalize_title

API_KEY = os.environ.get("SERPAPI_KEY", "").strip()
ENDPOINT = "https://serpapi.com/search.json"
AUTHORS_CACHE = "data/scholar_authors.json"

MIN_AGE_DAYS = int(os.environ.get("FC_MIN_AGE_DAYS", "25"))
MAX_QUERIES = int(os.environ.get("FC_MAX_QUERIES", "130"))
USE_BATCH = os.environ.get("FC_BATCH", "1") == "1"
RESOLVE_AUTHORS = os.environ.get("FC_RESOLVE_AUTHORS", "1") == "1"
AUTHOR_PAGES = int(os.environ.get("FC_AUTHOR_PAGES", "2"))
MIN_AUTHOR_PAPERS = int(os.environ.get("FC_MIN_AUTHOR_PAPERS", "2"))
SLEEP = float(os.environ.get("FC_SLEEP", "1.2"))
FORCE = os.environ.get("FC_FORCE", "") == "1"

_calls = 0  # SerpApi calls used this run


def budget_left():
    return _calls < MAX_QUERIES


def serp_get(params):
    """One SerpApi call. Counts against the per-run budget."""
    global _calls
    _calls += 1
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "fair-clustering-repo-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def cited_by(result):
    cb = ((result.get("inline_links") or {}).get("cited_by") or {})
    if "total" in cb:
        return cb.get("total")
    # author endpoint shape:
    cb2 = (result.get("cited_by") or {})
    return cb2.get("value")


# ---------------------------------------------------------------------------
# Author cache
# ---------------------------------------------------------------------------
def load_authors_cache():
    try:
        with open(AUTHORS_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_authors_cache(cache):
    os.makedirs(os.path.dirname(AUTHORS_CACHE), exist_ok=True)
    with open(AUTHORS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")


def split_authors(s):
    return [a.strip() for a in (s or "").replace(" and ", ", ").split(",") if a.strip()]


def resolve_author_id(name, cache):
    """Return a Scholar author_id for `name`, using/filling the cache. Cautious:
    only accepts a profile whose name matches closely."""
    key = name.lower().strip()
    if key in cache:                       # already known (id or None)
        return cache[key].get("author_id")
    if not RESOLVE_AUTHORS or not budget_left():
        return None
    try:
        data = serp_get({"engine": "google_scholar_profiles", "mauthors": name, "api_key": API_KEY})
    except Exception as e:
        print(f"  ! profiles({name}): {e}", file=sys.stderr)
        return None
    time.sleep(SLEEP)
    profiles = data.get("profiles") or []
    want = normalize_title(name)
    chosen = None
    for p in profiles:
        if normalize_title(p.get("name", "")) == want:
            chosen = p.get("author_id")
            break
    cache[key] = {"author_id": chosen, "name": name, "checked": datetime.date.today().isoformat()}
    return chosen


def fetch_author_articles(author_id):
    """All (title, cited_by, citation_id) for an author, up to AUTHOR_PAGES*100."""
    out = []
    for page in range(AUTHOR_PAGES):
        if not budget_left():
            break
        try:
            data = serp_get({"engine": "google_scholar_author", "author_id": author_id,
                             "num": "100", "start": str(page * 100), "api_key": API_KEY})
        except Exception as e:
            print(f"  ! author({author_id}) p{page}: {e}", file=sys.stderr)
            break
        time.sleep(SLEEP)
        arts = data.get("articles") or []
        out.extend(arts)
        if len(arts) < 100:
            break
    return out


# ---------------------------------------------------------------------------
# Fallback per-title / per-cluster lookup
# ---------------------------------------------------------------------------
def lookup_one(paper):
    """Return (count, cluster_id) for a single paper. One SerpApi call."""
    if paper.get("scholar_id"):
        data = serp_get({"engine": "google_scholar", "cluster": paper["scholar_id"], "api_key": API_KEY})
        res = data.get("organic_results") or []
        return (cited_by(res[0]) if res else None), paper["scholar_id"]
    data = serp_get({"engine": "google_scholar", "q": paper["title"], "num": "5", "api_key": API_KEY})
    res = data.get("organic_results") or []
    if not res:
        return None, ""
    want = normalize_title(paper["title"])
    best = res[0]
    for r in res:
        if normalize_title(r.get("title", "")) == want:
            best = r
            break
    return cited_by(best), best.get("result_id", "")


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
    stale.sort(key=lambda p: p.get("citations_updated") or "")   # oldest first
    by_title = {normalize_title(p["title"]): p for p in stale}
    print(f"{len(stale)} of {len(papers)} papers are stale (> {MIN_AGE_DAYS}d). "
          f"Budget: {MAX_QUERIES} SerpApi calls.")

    deltas = []
    done = set()

    def apply_update(p, count, cid):
        p["citations_updated"] = today
        if cid and not p.get("scholar_id"):
            p["scholar_id"] = cid
        old = p.get("citations", 0) or 0
        if count is not None and count != old:
            p["citations"] = count
            deltas.append((p["title"], old, count))
            print(f"  {old:>5} -> {count:<5}  {p['title'][:62]}")
        done.add(p["id"])

    # ---- Phase 1: author-batch ------------------------------------------------
    if USE_BATCH:
        cache = load_authors_cache()
        freq = {}
        for p in stale:
            for a in split_authors(p.get("authors", "")):
                freq[a] = freq.get(a, 0) + 1
        authors = sorted((a for a, n in freq.items() if n >= MIN_AUTHOR_PAPERS),
                         key=lambda a: -freq[a])
        print(f"Author-batch pass over {len(authors)} prolific author(s)…")
        for name in authors:
            if not budget_left() or len(done) >= len(stale):
                break
            aid = resolve_author_id(name, cache)
            if not aid:
                continue
            for art in fetch_author_articles(aid):
                p = by_title.get(normalize_title(art.get("title", "")))
                if p and p["id"] not in done:
                    apply_update(p, cited_by(art), art.get("citation_id", ""))
        save_authors_cache(cache)
        print(f"  matched {len(done)} paper(s) via author batch; {_calls} calls used so far.")

    # ---- Phase 2: budgeted per-title fallback --------------------------------
    remaining = [p for p in stale if p["id"] not in done]
    for p in remaining:
        if not budget_left():
            print(f"Budget reached ({MAX_QUERIES}); {len(remaining)} paper(s) left for next run.")
            break
        try:
            count, cid = lookup_one(p)
            apply_update(p, count, cid)
        except Exception as e:
            print(f"  ! {p['title'][:60]}: {e}", file=sys.stderr)
        time.sleep(SLEEP)

    save_papers(papers)
    changed = len(deltas)
    print(f"\nDone. Updated {changed} citation count(s). SerpApi calls used: {_calls}/{MAX_QUERIES}. "
          f"Refreshed {len(done)} paper(s).")

    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if changed else 'false'}\n")
        gh.write(f"count={changed}\n")
        gh.write(f"calls={_calls}\n")
    if changed:
        deltas.sort(key=lambda d: abs(d[2] - d[1]), reverse=True)
        with open("citation_summary.md", "w", encoding="utf-8") as f:
            f.write(f"### Google Scholar citation refresh — {today}\n\n")
            f.write(f"Updated **{changed}** paper(s) using **{_calls}** SerpApi call(s) "
                    f"(budget {MAX_QUERIES}; {len(done)} refreshed, stale-gated at {MIN_AGE_DAYS}d).\n\n")
            f.write("| Δ | was | now | paper |\n|---:|---:|---:|---|\n")
            for title, o, n in deltas[:100]:
                f.write(f"| {n - o:+d} | {o} | {n} | {title[:80]} |\n")


if __name__ == "__main__":
    main()
