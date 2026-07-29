#!/usr/bin/env python3
"""
refresh_citations.py — cautious Google Scholar citation refresh via SerpApi.

TWO-PHASE, BUDGET-AWARE DESIGN
------------------------------

  PHASE 1 — BULK SWEEP (cheap).  A handful of broad topic queries
    ("fair clustering", "socially fair clustering", "fairlets", ...) are paged
    through the Google Scholar search engine.  Each SerpApi call returns up to
    20 results (Scholar's hard per-page limit), so FC_SWEEP_PAGES=5 buys ~100
    hits for 5 calls.  Every hit carries its own title, authors, cluster id and
    citation count, so ONE call can refresh dozens of papers at once.  For a
    corpus that is mostly "fair clustering" papers this typically resolves the
    large majority of the database for ~40-60 calls instead of ~210.

  PHASE 2 — PRECISE RESIDUAL (exact).  Whatever the sweep did not confidently
    match (odd titles, off-topic venues, papers whose sweep value tripped the
    sanity guard) is looked up one paper at a time — by cached `scholar_id`
    cluster when we have one, else by a title search — exactly as before.

ACCURACY RULES (unchanged, applied to both phases)
  * A sweep hit is only accepted when its cluster id equals the paper's cached
    `scholar_id`, or its normalized title matches exactly, or its title overlaps
    >= 0.82 by tokens AND at least one author surname matches.
  * Among all matching hits (Scholar often lists several versions of a paper)
    we keep the HIGHEST citation count — the canonical merged entry.
  * SANITY GUARD: counts essentially never fall and never jump by orders of
    magnitude. A proposed DROP or implausible SPIKE is never written. From the
    sweep it is instead re-checked exactly in phase 2; if it survives that, it
    is surfaced in the PR under "Needs manual check".

Env (all optional except the key):
  SERPAPI_KEY        required — https://serpapi.com/manage-api-key
  FC_MIN_AGE_DAYS    skip papers refreshed more recently than this (default 25)
  FC_MAX_QUERIES     hard cap on TOTAL SerpApi calls this run (default 200)
  FC_SWEEP           "0" to disable the bulk sweep (default on)
  FC_SWEEP_PAGES     pages of 20 results per sweep query (default 5 => ~100 hits)
  FC_SWEEP_CALLS     cap on calls spent inside the sweep (default 60)
  FC_SWEEP_QUERIES   "|"-separated override of the sweep query list
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

SWEEP_ON = os.environ.get("FC_SWEEP", "1") != "0"
SWEEP_PAGES = int(os.environ.get("FC_SWEEP_PAGES", "5"))     # 20 results per page
SWEEP_CALLS = int(os.environ.get("FC_SWEEP_CALLS", "60"))
PAGE_SIZE = 20                                               # Scholar's maximum

DEFAULT_SWEEP_QUERIES = [
    "fair clustering",
    "algorithmic fair clustering",
    "fairness in clustering",
    "fair k-means clustering",
    "fair k-center k-median approximation",
    "socially fair clustering",
    "individually fair clustering",
    "proportionally fair clustering core",
    "fair correlation clustering",
    "fair clustering coreset streaming",
    "fairlets fair clustering",
    "deep fair clustering spectral",
]
SWEEP_QUERIES = [q.strip() for q in os.environ.get("FC_SWEEP_QUERIES", "").split("|") if q.strip()] \
    or DEFAULT_SWEEP_QUERIES

_calls = 0
_sweep_calls = 0


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


def classify(old, new):
    """'apply' | 'drop' | 'spike' | 'none' — the sanity guard."""
    if new is None:
        return "none"
    if new < old - DECREASE_TOL:
        return "drop"
    if old >= 10 and new > old * SPIKE_FACTOR and (new - old) > SPIKE_ABS:
        return "spike"
    return "apply"


# --------------------------------------------------------------------------
# PHASE 1 — bulk sweep
# --------------------------------------------------------------------------
def sweep(stale):
    """Page through broad topic queries and harvest citation counts in bulk.

    Returns {paper_index: (best_count, cluster_id)} for confidently matched
    papers. Costs at most min(FC_SWEEP_CALLS, remaining budget) SerpApi calls
    no matter how many papers get matched."""
    global _sweep_calls
    budget = min(SWEEP_CALLS, MAX_QUERIES)

    # Pre-index the stale set so each incoming result is cheap to route.
    by_norm, by_cid, meta = {}, {}, []
    for i, p in enumerate(stale):
        by_norm.setdefault(normalize_title(p.get("title", "")), []).append(i)
        if p.get("scholar_id"):
            by_cid.setdefault(str(p["scholar_id"]), []).append(i)
        meta.append((tokens(p.get("title", "")), surnames(p.get("authors", ""))))

    found = {}

    def route(r):
        count = cited_by(r)
        if count is None:
            return
        cid = cluster_id(r) or r.get("result_id", "")
        rtitle = r.get("title", "")
        matched = set(by_cid.get(str(cid), [])) | set(by_norm.get(normalize_title(rtitle), []))
        if not matched:                       # fuzzy fallback, author-verified
            rtok, rsur = tokens(rtitle), surnames(result_authors(r))
            if rtok and rsur:
                for i, (ptok, psur) in enumerate(meta):
                    if not ptok or not (rsur & psur):
                        continue
                    if len(rtok & ptok) / len(rtok | ptok) >= 0.82:
                        matched.add(i)
        for i in matched:
            prev = found.get(i)
            if prev is None or count > prev[0]:
                found[i] = (count, cid)

    for q in SWEEP_QUERIES:
        if _calls >= budget:
            break
        for page in range(SWEEP_PAGES):
            if _calls >= budget:
                break
            try:
                data = serp_get({"engine": "google_scholar", "q": q, "hl": "en",
                                 "num": str(PAGE_SIZE), "start": str(page * PAGE_SIZE),
                                 "api_key": API_KEY})
            except Exception as e:
                print(f"  ! sweep '{q}' p{page}: {e}", file=sys.stderr)
                break
            _sweep_calls += 1
            res = data.get("organic_results") or []
            for r in res:
                route(r)
            time.sleep(SLEEP)
            if len(res) < PAGE_SIZE:          # end of this query's results
                break
        print(f"  sweep '{q}': {len(found)}/{len(stale)} stale papers matched so far "
              f"({_sweep_calls} calls)")
        if len(found) == len(stale):
            break

    return found


def best_count(paper):
    """PHASE 2 — exact per-paper lookup. Returns (count, cluster_id, matched).
    One SerpApi call. Among title-matching results, prefers the one whose
    AUTHORS overlap this paper's authors, then the highest citation count."""
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
    verified = [r for r in cands if author_overlap(r, paper) > 0]
    pool = verified or cands
    best = max(pool, key=lambda r: (author_overlap(r, paper), cited_by(r) or -1))
    cid = cluster_id(best) or best.get("result_id", "")
    return cited_by(best), cid, True


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

    applied, flagged, unmatched, deferred = [], [], [], []
    resolved = set()

    # ---- Phase 1: bulk sweep --------------------------------------------
    if SWEEP_ON and stale:
        print(f"Sweep: {len(SWEEP_QUERIES)} topic queries x up to {SWEEP_PAGES} pages "
              f"({PAGE_SIZE}/page), cap {SWEEP_CALLS} calls.")
        for idx, (new, cid) in sweep(stale).items():
            p = stale[idx]
            old = p.get("citations", 0) or 0
            if cid and not p.get("scholar_id"):
                p["scholar_id"] = cid
            if classify(old, new) == "apply":
                p["citations_updated"] = today
                resolved.add(idx)
                if new != old:
                    p["citations"] = new
                    applied.append((p["title"], old, new))
                    print(f"  {old:>5} -> {new:<5}  {p['title'][:60]}   [sweep]")
            # A drop/spike seen in the sweep may just be a low-cited duplicate
            # version, so leave the paper unresolved: phase 2 checks it exactly.
        print(f"Sweep resolved {len(resolved)}/{len(stale)} papers in {_sweep_calls} calls.")

    # ---- Phase 2: precise residual ---------------------------------------
    residual = [p for i, p in enumerate(stale) if i not in resolved]
    print(f"Residual: {len(residual)} paper(s) to look up individually "
          f"({MAX_QUERIES - _calls} calls left).")
    for n, p in enumerate(residual):
        if _calls >= MAX_QUERIES:
            deferred = [q["title"] for q in residual[n:]]
            print(f"Budget reached ({MAX_QUERIES}); {len(deferred)} paper(s) left for next run.")
            break
        old = p.get("citations", 0) or 0
        try:
            new, cid, matched = best_count(p)
        except Exception as e:
            print(f"  ! {p['title'][:60]}: {e}", file=sys.stderr)
            time.sleep(SLEEP)
            continue

        if not matched:
            unmatched.append((p.get("id", ""), p["title"]))
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
    precise_calls = _calls - _sweep_calls
    print(f"\nApplied {len(applied)}, flagged {len(flagged)}, unmatched {len(unmatched)}, "
          f"deferred {len(deferred)}. SerpApi calls: {_calls}/{MAX_QUERIES} "
          f"({_sweep_calls} sweep + {precise_calls} precise).")

    changed = len(applied) > 0 or len(flagged) > 0 or len(unmatched) > 0
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if changed else 'false'}\n")
        gh.write(f"count={len(applied)}\n")
        gh.write(f"flagged={len(flagged)}\n")
        gh.write(f"unmatched={len(unmatched)}\n")
        gh.write(f"calls={_calls}\n")
        gh.write(f"sweep_calls={_sweep_calls}\n")

    if changed:
        with open("citation_summary.md", "w", encoding="utf-8") as f:
            f.write(f"### Google Scholar citation refresh — {today}\n\n")
            f.write(f"Applied **{len(applied)}** update(s) using **{_calls}** SerpApi call(s) "
                    f"— {_sweep_calls} in the bulk topic sweep (up to {PAGE_SIZE * SWEEP_PAGES} "
                    f"hits per query) + {precise_calls} exact per-paper lookup(s) "
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
                f.write(f"\n### \u2753 No confident title match \u2014 verify manually ({len(unmatched)})\n\n")
                f.write("These papers were left unchanged because no Google Scholar result matched "
                        "their title (and authors) with enough confidence. Check each one by hand; if "
                        "you find its Scholar entry, paste the numeric `cluster` id from its "
                        "\u201cCited by\u201d link into that paper's `scholar_id` in `data/papers.json` so "
                        "future runs match it exactly.\n\n")
                f.write("| # | id | paper |\n|---:|---|---|\n")
                for i, (pid, title) in enumerate(unmatched, 1):
                    f.write(f"| {i} | `{pid}` | {title[:90]} |\n")
            if deferred:
                f.write(f"\n### \u23ed Deferred to next run \u2014 call budget reached ({len(deferred)})\n\n")
                for t in deferred[:50]:
                    f.write(f"- {t[:90]}\n")


if __name__ == "__main__":
    main()
