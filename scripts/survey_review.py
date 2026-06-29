#!/usr/bin/env python3
"""
survey_review.py — mark AI-drafted survey sections as author-reviewed.

Flips entries in survey/ai_status.json. When a section is reviewed (true), the
website hides its "AI-drafted" banner and tag. Driven by the
"Survey: mark AI section reviewed" workflow (workflow_dispatch), which only
repository collaborators can run — so this is an admin-only action.

Inputs via env:
  FC_SECTION   section id, or "all"  (required)
  FC_REVIEWED  "true" (default) or "false" to undo
"""
import json
import os
import sys

PATH = "survey/ai_status.json"
SECTIONS = ["abstract", "preliminaries", "proportionality", "techniques",
            "future-directions", "fig-taxonomy", "tab-results"]


def main():
    section = os.environ.get("FC_SECTION", "").strip()
    reviewed = os.environ.get("FC_REVIEWED", "true").strip().lower() in ("1", "true", "yes")
    if not section:
        sys.exit("FC_SECTION is required.")

    with open(PATH, encoding="utf-8") as f:
        status = json.load(f)

    targets = SECTIONS if section == "all" else [section]
    changed = []
    for s in targets:
        if s not in SECTIONS:
            sys.exit(f"Unknown section '{s}'. Valid: {', '.join(SECTIONS)}, all")
        if status.get(s) != reviewed:
            status[s] = reviewed
            changed.append(s)

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)
        f.write("\n")

    verb = "reviewed" if reviewed else "unreviewed (AI tag restored)"
    print(f"Marked {verb}: {', '.join(changed) if changed else '(no change)'}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as gh:
        gh.write(f"changed={'true' if changed else 'false'}\n")
        gh.write(f"summary={verb}: {', '.join(changed) or 'none'}\n")


if __name__ == "__main__":
    main()
