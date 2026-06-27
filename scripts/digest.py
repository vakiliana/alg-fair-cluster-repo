#!/usr/bin/env python3
"""
digest.py — biweekly maintenance digest for the admin.

Pulls together everything that changed (or is waiting on you) and posts a single
summary issue you get notified about:

  * open issues labelled paper-submission / data-correction / tag-proposal
    (the things awaiting your decision),
  * pull requests opened or merged in the last ~15 days (discovery + citations),
  * papers still flagged ai_labeled = pending verification,
  * a couple of corpus stats.

Runs on GitHub Actions with the built-in GITHUB_TOKEN — no extra secrets.
Set DIGEST_ASSIGNEE / DIGEST_EMAIL in the workflow to control delivery.

Stdlib only.
"""
import datetime
import json
import os
import urllib.parse
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "vakiliana/alg-fair-cluster-repo")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
WINDOW_DAYS = int(os.environ.get("DIGEST_WINDOW_DAYS", "15"))
ASSIGNEE = os.environ.get("DIGEST_ASSIGNEE", "").strip()


def gh(path, params=None, method="GET", payload=None):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fair-clustering-repo-bot/1.0",
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def open_issues(label):
    try:
        items = gh(f"/repos/{REPO}/issues", {"state": "open", "labels": label, "per_page": 50})
        # /issues returns PRs too; drop them.
        return [i for i in items if "pull_request" not in i]
    except Exception as e:
        print(f"  ! issues({label}): {e}")
        return []


def recent_prs():
    try:
        prs = gh(f"/repos/{REPO}/pulls", {"state": "all", "sort": "updated", "direction": "desc", "per_page": 30})
    except Exception as e:
        print(f"  ! pulls: {e}")
        return [], []
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=WINDOW_DAYS)
    opened, merged = [], []
    for pr in prs:
        upd = datetime.datetime.strptime(pr["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
        if upd < cutoff:
            continue
        if pr.get("merged_at"):
            merged.append(pr)
        elif pr["state"] == "open":
            opened.append(pr)
    return opened, merged


def corpus_stats():
    try:
        papers = json.load(open("data/papers.json", encoding="utf-8"))
    except Exception:
        return None
    pending = [p for p in papers if p.get("status") == "pending-review"]
    ai = [p for p in papers if p.get("ai_labeled")]
    return {"total": len(papers), "pending": len(pending), "ai": len(ai)}


def main():
    today = datetime.date.today().isoformat()
    subs = open_issues("paper-submission")
    corr = open_issues("data-correction")
    tags = open_issues("tag-proposal")
    opened, merged = recent_prs()
    stats = corpus_stats()

    def issue_lines(items):
        return "\n".join(f"- [#{i['number']}]({i['html_url']}) {i['title']}" for i in items) or "_none_"

    def pr_lines(items):
        return "\n".join(f"- [#{p['number']}]({p['html_url']}) {p['title']}" for p in items) or "_none_"

    md = []
    md.append(f"## 🗓 Maintenance digest — {today}\n")
    md.append("### ⏳ Awaiting your review\n")
    md.append(f"**New-paper submissions** ({len(subs)})\n{issue_lines(subs)}\n")
    md.append(f"**Correction requests** ({len(corr)})\n{issue_lines(corr)}\n")
    md.append(f"**New-tag proposals — verify before adding** ({len(tags)})\n{issue_lines(tags)}\n")
    md.append(f"### 🔀 Pull requests (last {WINDOW_DAYS} days)\n")
    md.append(f"**Open (discovery / citations)** ({len(opened)})\n{pr_lines(opened)}\n")
    md.append(f"**Merged** ({len(merged)})\n{pr_lines(merged)}\n")
    if stats:
        md.append("### 📊 Corpus\n")
        md.append(f"- Total papers: **{stats['total']}**")
        md.append(f"- Pending review (`status: pending-review`): **{stats['pending']}**")
        md.append(f"- Still AI-labeled (unverified tags/notes): **{stats['ai']}**\n")
    md.append("---\n_Posted automatically. Reply here or jump into the linked issues/PRs to act._")
    body = "\n".join(md)

    # Write to disk (email step / artifact can pick it up).
    with open("digest.md", "w", encoding="utf-8") as f:
        f.write(body)

    if not TOKEN:
        print("No GITHUB_TOKEN — wrote digest.md only.")
        print(body)
        return

    payload = {"title": f"🗓 Maintenance digest — {today}", "body": body, "labels": ["digest", "automated"]}
    if ASSIGNEE:
        payload["assignees"] = [ASSIGNEE]
    try:
        created = gh(f"/repos/{REPO}/issues", method="POST", payload=payload)
        print(f"Opened digest issue #{created['number']}: {created['html_url']}")
    except Exception as e:
        print(f"  ! failed to create digest issue: {e}\n\n{body}")


if __name__ == "__main__":
    main()
