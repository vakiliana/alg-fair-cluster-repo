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
  discover.py            monthly: find new papers  → PR
  refresh_citations.py   monthly: Google Scholar counts via SerpApi → PR
  digest.py              monthly: summary of what's awaiting you → issue

.github/workflows/
  discover.yml         cron: 5th of month (discovery)
  citations.yml        cron: 5th of month (citation refresh)
  digest.yml           cron: 6th of month (admin digest)
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
| `ai_notes` | `true` = the Definition / Contribution / Open-problems were drafted automatically and **not yet verified**; the expanded card shows a gold **AI-generated details · unverified** badge. Set it to `false` once you've checked the notes and the badge disappears. (There is no separate tag-level badge — only the details one.) |
| `ai_labeled` | legacy flag, no longer shown on the site; safe to ignore. |
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

## 3. The monthly approval routine (≈10 min)

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
  current discovery PR), then close the issue. If the entry was AI-drafted,
  flip `ai_notes` to `false` once you've verified it.
- **`tag-proposal`** — the reader asked for a *new* tag the taxonomy doesn't
  have yet. **Verify before adding:** decide whether it's worth a new facet
  value; if so, add it to `WORK_NATURES` (or the notion list) in
  `scripts/fc_lib.py` *and* the `NATURES` / `NOTIONS` arrays in the site, then
  apply it. Existing-tag changes need no such gate.

> The **AI-generated details · unverified** badge (gold) marks entries whose
> Definition / Contribution / Open-problems the bot drafted. Clearing `ai_notes`
> (to `false`) certifies the notes as human-checked — the badge then disappears
> on the live site. It only ever shows when the entry actually has notes.

> **Tip:** you can trigger a scan any time from the **Actions** tab →
> *Discover new papers* → **Run workflow** (no need to wait for the cron).

---

## 4. The monthly citation refresh

On the 1st, the citation job refreshes Google Scholar counts (via SerpApi) and
opens a PR **"Monthly citation refresh (N applied, M flagged)"**. Skim it, then
merge.

**Accuracy is enforced, so a bad scrape can't silently corrupt counts:**

1. **Title-matched, canonical pick.** Each paper is looked up by a Scholar
   *search*; only results whose title matches are kept, and the **highest-cited**
   one is used (Scholar's merged entry, not a low-cited preprint duplicate).
2. **Sanity guard.** Citation counts don't fall or jump 40× in a month. Any
   proposed change that **drops** the count or **spikes** implausibly is treated
   as a likely mismatch — it is **not written**, and instead listed in the PR
   under **"⚠️ Needs manual check"** for you to verify by hand. (This is what
   would have caught the earlier 301→41 and 66→2851 errors.)
3. **Cautious API use.** A staleness gate (`FC_MIN_AGE_DAYS`, default 25) skips
   recently-refreshed papers; the rest go oldest-first; and `FC_MAX_QUERIES`
   (default 200) caps calls per run, so a large corpus refreshes gradually. The
   PR title reports calls used.

When a flagged change is actually real, just edit the count in `data/papers.json`
(or fix the paper's `scholar_id`) — merging the PR applies the safe updates and
leaves the flagged ones for you.

- Per-paper **cluster ids** are cached in `scholar_id` for exact, cheap
  re-lookups. A match looks wrong? Clear `scholar_id` (re-matches by title) or
  paste the correct cluster id by hand.
- Knobs live in `.github/workflows/citations.yml`
  (`FC_MIN_AGE_DAYS`, `FC_MAX_QUERIES`, `FC_DECREASE_TOL`, `FC_SPIKE_FACTOR`).
  Force a full refresh with `FC_FORCE=1`.
- Prefer fully automatic? Set `OPEN_PR: "false"` to commit straight to `main`.

---

## 5. Cadence summary

| Job | Schedule | Output | Your action |
|---|---|---|---|
| Discovery (arXiv + DBLP) | 1st, 06:00 UTC | PR with new candidates | Review tags + notes, merge |
| Citation refresh (SerpApi/Scholar) | 1st, 06:00 UTC | PR with citation deltas | Skim, merge |
| **Admin digest** | 2nd, 07:00 UTC | summary issue (what's awaiting you) | Read, act on links |
| Site submissions / corrections / tag proposals | on demand (users) | GitHub issues (`needs-approval`) | Triage into `papers.json` |

Change a schedule by editing the `cron:` line in the relevant workflow
([crontab.guru](https://crontab.guru) helps).

---

## 6. Editing a paper — the smooth way (no local git)

**Recommended: never edit `data/papers.json` on your laptop.** Local edits race
with the bot's commits to `main`, which is what causes `fetch first` /
rebase / merge-conflict headaches. Instead, make every change *on GitHub*, three
ways — pick whichever fits:

**a) One-click "Edit a paper" workflow** (best for a quick fix like a citation
count). Actions tab → **Edit a paper** → **Run workflow** → fill the form
(paper id or title, field, new value) → it opens a PR (or commits directly if
you tick the box). Example: paper `BackursIOSVW19`, field `citations`,
value `335`. Setting notes this way auto-clears the AI-details flag (`ai_notes`)
and stamps the date. No clone, no conflict.

**b) Edit the file in the browser.** Open `data/papers.json` on github.com →
pencil icon → change the record → "Commit" (to a new branch → PR, or straight to
`main`). GitHub commits on top of the current tip, so it never conflicts.

**c) Reader "Suggest an edit" issues.** Apply those by doing (a) or (b).

**If you DO keep a local clone**, make pulls painless by only ever *reading*
locally and pushing code (scripts/site), not data. When you must pull:

```bash
git pull --rebase --autostash      # rebase your work on top of the bot's commits
# data/papers.json is machine-generated — if it ever conflicts, just take main's:
git checkout --theirs data/papers.json && git add data/papers.json && git rebase --continue
```

To go fully clean and match the remote exactly (discards local changes):
`git fetch origin && git reset --hard origin/main`.

> **Why this works:** the repo has two writers — you and the automation. Keeping
> all *data* edits on GitHub means there's effectively one writer to `main` at a
> time (whoever merges next), so fast-forward pushes just work.

To add a paper manually, the discovery PR is the normal path; or copy an existing
block in the browser editor and fill the fields — only `title` is strictly
required (missing `bib_entry` falls back to generated BibTeX on download).

---

## 7. Notes & limits

- **Google Scholar has no official API.** SerpApi is the reliable, ToS-clean
  way to read Scholar from CI. A direct scrape from Actions would be blocked
  within days — that's why the pipeline routes through your SerpApi key.
- **arXiv/DBLP discovery** is title+abstract keyword based; the PR gate is what
  keeps quality high. Tune the queries in `discover.py` (`ARXIV_QUERIES` /
  `DBLP_QUERIES`) and the relevance test in `fc_lib.is_fair_clustering`.
- Scripts are **pure stdlib** — no `pip install`, fast cold starts.
