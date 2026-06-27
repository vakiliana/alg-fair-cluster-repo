# Maintaining the Fair Clustering Repository

This repo is a **living index** of algorithmic fair-clustering papers. The site
is static (GitHub Pages); everything it shows comes from a single data file,
and two scheduled jobs keep that file fresh. You stay in control: every
automated change arrives as a **pull request** you review and merge.

---

## 1. How it fits together

```
data/papers.json     ← the single source of truth (one JSON array of papers)
index.html           ← the website (reads data/papers.json at load time)
support.js           ← runtime for the site (ships next to index.html)
logo.png             ← header logo

scripts/
  fc_lib.py              shared helpers + the tagging taxonomy
  discover.py            biweekly: find new papers  → PR
  refresh_citations.py   monthly: Google Scholar counts via SerpApi → PR
  digest.py              biweekly: summary of what's awaiting you → issue

.github/workflows/
  discover.yml         cron: 1st & 15th  (biweekly discovery)
  citations.yml        cron: 1st of month (citation refresh)
  digest.yml           cron: 2nd & 16th  (biweekly admin digest)
```

Each record in `data/papers.json` carries the two **tag facets** plus the
**expandable notes**:

| field | meaning |
|---|---|
| `fairness_notion` | Facet 1 — *the definition*: Group (balance) / Individual / Socially fair (min-max) / Proportional (core) |
| `work_nature` | Facet 2 — *nature of work* (array): Theory / Algorithms / Deep-ML / Robustness / Survey |
| `definition` | short prose: the fairness notion the paper uses |
| `contribution` | short prose: what the paper adds |
| `open_problems` | array of strings — shown as the expandable list |
| `citations`, `citations_updated`, `scholar_id` | maintained by the citation job |
| `ai_labeled` | `true` = the fairness-notion / work-nature tags (and any notes) were generated automatically and **not yet verified**; the site shows a dashed **AI-labeled** badge. Set it to `false` when you've checked the entry. |
| `status` | `pending-review` while a discovered paper awaits your sign-off; clear it (or leave it) on merge |

---

## 2. One-time setup

1. **Add the SerpApi key.** Repo → *Settings → Secrets and variables → Actions →
   New repository secret*: name `SERPAPI_KEY`, value = your key from
   <https://serpapi.com/manage-api-key>.
2. **Allow Actions to open PRs.** *Settings → Actions → General → Workflow
   permissions* → enable **Read and write permissions** and
   **Allow GitHub Actions to create and approve pull requests**.
3. **Labels (optional).** Create `paper-submission`, `data-correction`,
   `tag-proposal`, `citations`, `automated`, `digest` so the queues are easy to
   filter. To get the digest issue assigned to you, set `DIGEST_ASSIGNEE` to
   your username in `.github/workflows/digest.yml`.
4. **Pages.** *Settings → Pages* → deploy from `main` (root). Confirm the live
   site loads `data/papers.json`.

That's it — the cron schedules in the two workflow files do the rest.

---

## 3. The biweekly approval routine (≈10 min)

When the discovery job runs it opens a PR titled
**"N new fair-clustering paper(s) for review"**.

1. Open the PR → **Files changed**. Each new paper is a JSON block appended to
   `data/papers.json` with `"status": "pending-review"`.
2. For each one:
   - **Keep or drop** — delete the block if it's off-topic (the relevance gate
     is good but not perfect).
   - **Fix the tags** — `fairness_notion` is a single best-guess; correct it,
     and adjust the `work_nature` array.
   - **Write the notes** (optional but the point of the repo) — fill
     `definition`, `contribution`, and `open_problems`.
   - Optionally set `"status": ""` to mark it fully curated.
3. **Merge.** The site updates within a minute or two.

User submissions from the site's *“Submit a publication”* form arrive as
**issues** labelled `paper-submission` — triage those the same way (add the
entry, or just close if duplicate).

### Reader corrections & tag proposals

Every paper has a **“Suggest an edit”** button (in its expanded panel). A reader
can rewrite the Definition / Contribution / Open-problems, re-pick the fairness
notion, toggle the work-nature tags, or **propose a brand-new tag**. Submitting
opens a pre-filled issue showing *current → proposed* for each field:

- **`data-correction`** — edits using the existing taxonomy. Apply the ones you
  agree with by editing `data/papers.json` (directly on `main`, or in the
  current discovery PR), then close the issue. If the entry was `ai_labeled`,
  flip it to `false` once you've verified it.
- **`tag-proposal`** — the reader asked for a *new* tag the taxonomy doesn't
  have yet. **Verify before adding:** decide whether it's worth a new facet
  value; if so, add it to `WORK_NATURES` (or the notion list) in
  `scripts/fc_lib.py` *and* the `NATURES` / `NOTIONS` arrays in the site, then
  apply it. Existing-tag changes need no such gate.

> The **AI-labeled** badge marks entries whose tags/notes the bot guessed.
> Clearing `ai_labeled` (to `false`) is how you certify an entry as
> human-checked — the badge then disappears on the live site.

> **Tip:** you can trigger a scan any time from the **Actions** tab →
> *Discover new papers* → **Run workflow** (no need to wait for the cron).

---

## 4. The monthly citation refresh

On the 1st, the citation job queries Google Scholar (via SerpApi) for every
paper and opens a PR **"Monthly citation refresh (N updated)"** containing a
delta table (Δ, was, now, paper). Skim it for anything wild (a mis-matched
Scholar cluster), then merge.

- The first run also stores each paper's Scholar **cluster id** in
  `scholar_id`, so subsequent runs are exact and cheaper.
- Prefer fully automatic? In `.github/workflows/citations.yml` set
  `OPEN_PR: "false"` and it commits straight to `main`.
- A paper's Scholar match looks wrong? Clear its `scholar_id` (re-matches by
  title next run) or paste the correct cluster id by hand.

---

## 5. Cadence summary

| Job | Schedule | Output | Your action |
|---|---|---|---|
| Discovery (arXiv + DBLP) | 1st & 15th, 06:00 UTC | PR with new candidates | Review tags + notes, merge |
| Citation refresh (SerpApi/Scholar) | 1st, 06:00 UTC | PR with citation deltas | Skim, merge |
| **Admin digest** | 2nd & 16th, 07:00 UTC | summary issue (what's awaiting you) | Read, act on links |
| Site submissions / corrections / tag proposals | on demand (users) | GitHub issues | Triage into `papers.json` |

Change a schedule by editing the `cron:` line in the relevant workflow
([crontab.guru](https://crontab.guru) helps).

---

## 6. Editing a paper by hand

Everything is just `data/papers.json`. Edit a record, commit to `main`, done.
To add a paper manually, copy an existing block and fill the fields — only
`title` is strictly required; missing `bib_entry` falls back to BibTeX
generated from the metadata when someone downloads it.

---

## 7. Notes & limits

- **Google Scholar has no official API.** SerpApi is the reliable, ToS-clean
  way to read Scholar from CI. A direct scrape from Actions would be blocked
  within days — that's why the pipeline routes through your SerpApi key.
- **arXiv/DBLP discovery** is title+abstract keyword based; the PR gate is what
  keeps quality high. Tune the queries in `discover.py` (`ARXIV_QUERIES` /
  `DBLP_QUERIES`) and the relevance test in `fc_lib.is_fair_clustering`.
- Scripts are **pure stdlib** — no `pip install`, fast cold starts.
