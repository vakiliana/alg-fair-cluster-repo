"""
Shared helpers for the Fair Clustering Repository maintenance pipeline.

Pure standard library (no pip installs) so the GitHub Actions runners stay fast.

The canonical data file is data/papers.json — a JSON array of paper records:

    {
      "id":               "DBLPKey or arXivId",   # stable identifier
      "title":            "...",
      "authors":          "A, B, C",
      "year":             2024,
      "venue":            "NeurIPS",
      "citations":        42,
      "link":             "https://...",           # canonical landing page
      "pdf":              "https://...",
      "bib_link":         "https://dblp.org/rec/...",
      "bib_entry":        "@inproceedings{...}",    # raw BibTeX (optional)
      "scholar_id":       "1234567890",             # SerpApi cluster id (filled by refresh)
      "fairness_notion":  "Group fairness (balance)",
      "work_nature":      ["Theory / approximation", ...],
      "tags":             [],
      "definition":       "",                        # maintainer-authored
      "contribution":     "",                        # maintainer-authored
      "open_problems":    [],                         # maintainer-authored
      "citations_updated":"2026-06-01",
      "added":            "2025-01-01",
      "status":           ""                          # "" = published; "pending-review" = added by discovery
    }
"""
import json
import os
import re

DATA_PATH = os.environ.get("FC_DATA_PATH", "data/papers.json")

# --------------------------------------------------------------------------
# Tagging taxonomy  (keep in sync with the website's two facets)
# --------------------------------------------------------------------------
FAIRNESS_NOTIONS = [
    "Group fairness (balance)",
    "Individual fairness",
    "Socially fair (min-max)",
    "Proportional / core",
]
WORK_NATURES = [
    "Theory / approximation",
    "Algorithms / systems",
    "Deep / ML",
    "Robustness / attacks",
    "Survey / position",
]


def normalize_title(t):
    """Lower-case, strip punctuation, collapse whitespace — used for dedup."""
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def guess_fairness_notion(title):
    t = (title or "").lower()
    if re.search(r"social(ly)? fair|rawlsian|min[- ]?max", t):
        return "Socially fair (min-max)"
    if re.search(r"individual|equitable", t):
        return "Individual fairness"
    if re.search(r"proportional|\bcore\b|social choice|non-centroid", t):
        return "Proportional / core"
    return "Group fairness (balance)"


def guess_work_nature(title):
    t = (title or "").lower()
    tags = []
    def add(x):
        if x not in tags:
            tags.append(x)
    if re.search(r"survey|overview|critique|caveats|story so far|\bsok\b|whither|future directions|perspective", t):
        add("Survey / position")
    if re.search(r"deep|neural|spectral|transformer|contrastive|variational|autoencoder|visual|multi-view|representation|\bkan\b", t):
        add("Deep / ML")
    if re.search(r"approximation|polynomial|\bfpt\b|np-?hard|coreset|streaming|mapreduce|local search|linear program|complexity|tight|constant-?factor|guarantee", t):
        add("Theory / approximation")
    if re.search(r"attack|defense|adversarial|antidote|robust|uncertainty", t):
        add("Robustness / attacks")
    if re.search(r"algorithm|scalable|efficient|\bfast\b|distributed|sliding window|online", t):
        add("Algorithms / systems")
    if not tags:
        add("Algorithms / systems")
    return tags


def is_fair_clustering(title, abstract=""):
    """Heuristic relevance gate for discovery — must mention fairness AND clustering."""
    blob = (title + " " + abstract).lower()
    has_fair = "fair" in blob or "fairness" in blob
    has_cluster = any(k in blob for k in [
        "cluster", "k-means", "k-median", "k-center", "kmeans",
        "facility location", "correlation clustering",
    ])
    return has_fair and has_cluster


# --------------------------------------------------------------------------
# Load / save
# --------------------------------------------------------------------------
def load_papers(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_papers(papers, path=DATA_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
        f.write("\n")


def existing_title_index(papers):
    """Map normalized title -> record, for dedup."""
    return {normalize_title(p.get("title", "")): p for p in papers}


def new_record(title, **kw):
    """Build a fully-formed record with sensible defaults + heuristic tags."""
    rec = {
        "id": kw.get("id", ""),
        "title": title,
        "authors": kw.get("authors", ""),
        "year": kw.get("year", None),
        "venue": kw.get("venue", ""),
        "citations": kw.get("citations", 0),
        "link": kw.get("link", ""),
        "pdf": kw.get("pdf", ""),
        "bib_link": kw.get("bib_link", ""),
        "bib_entry": kw.get("bib_entry", ""),
        "scholar_id": "",
        "fairness_notion": guess_fairness_notion(title),
        "work_nature": guess_work_nature(title),
        "tags": [],
        "definition": "",
        "contribution": "",
        "open_problems": [],
        "ai_labeled": True,   # heuristic fairness_notion / work_nature — awaiting human verification
        "ai_notes": False,    # set True if Definition/Contribution/Open-problems are AI-drafted
        "citations_updated": "",
        "added": kw.get("added", ""),
        "status": kw.get("status", "pending-review"),
    }
    return rec
