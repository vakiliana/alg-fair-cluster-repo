# Syncing the studio ↔ GitHub without conflicts

You have **two writers** to this repo, and that's the whole source of the
`fetch first` / rebase / merge-conflict pain:

1. **The design studio** (where the site, scripts, workflows, and big data
   curation are produced) → hands you files.
2. **GitHub Actions bots + the browser** (monthly citation refresh, discovery,
   the *Edit a paper* workflow) → commit to `main` on their own.

The fix is to give every file **one owner** so the two writers never touch the
same thing at the same time.

## File ownership

| Path | Owner | Direction | Conflicts? |
|---|---|---|---|
| `index.html`, `*.dc.html`, `support.js`, `logo.*` | **Studio** | studio → GitHub (overwrite freely) | Never — bots never touch these |
| `scripts/**`, `.github/workflows/**`, `*.md` | **Studio** | studio → GitHub (overwrite freely) | Never |
| `data/papers.json` | **Shared** | mostly bots/browser; studio only for big passes | Only possible conflict point |

Because everything except `data/papers.json` is studio-owned and bot-untouched,
**pushing those files can never conflict.** Copy them over, commit, push — done.

## The one shared file: `data/papers.json`

Normal upkeep should **not** go through the studio:

- **Citations** → the monthly `citations.yml` job (SerpApi) writes them.
- **Single fixes** (a count, a tag, a note) → the **Edit a paper** workflow
  (Actions tab) or edit the file in the browser. No clone involved.

Reserve the studio for **big curation passes** (e.g. the LaTeX rewrite, bulk
re-tagging). When you do one, keep it safe by basing it on the latest data:
ask for the pass to start from the **current `main` `data/papers.json`**, so the
returned file already contains the bots' latest citations and only changes the
fields the pass was about.

## Recommended push routine (no local rebases)

Land studio bundles through a branch + PR instead of pushing to `main` from a
local clone:

1. On github.com: **Add file → Upload files** (or create a branch), drop in the
   files from the studio bundle, keeping their paths.
2. Commit to a branch like `studio-update`, open a PR.
3. GitHub shows a clean diff. The only file that could ever flag a conflict is
   `data/papers.json`; resolve it in the web UI (keep bot citations, take studio
   titles/notes) and merge.

This keeps `main` linear, runs nothing locally, and means a Personal Access
Token with `workflow` scope is only needed once (for the `.github/workflows/**`
files).

### If you prefer a local clone

```bash
git pull --rebase --autostash        # get the bots' commits first
# copy the studio bundle over your working tree (keep paths), then:
git status                           # review exactly what changed
git add -A && git commit -m "Studio update: <what>"
git push
```

`git status` is your safety net: unchanged files produce no diff, so a wholesale
copy only ever stages real changes. If the diff shows citation counts going
*backwards* in `data/papers.json`, that's the studio file being older than
`main` — keep `main`'s numbers for those records.
