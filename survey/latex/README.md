# Fair Clustering Survey (Part I) — LaTeX source

Augmented, compile-ready LaTeX for *Fair Clustering: Concepts, Methods, and Algorithms (Part I)*.
It mirrors the web version (\`survey.html\`); the two are kept in sync in content.

## Compile

\`\`\`bash
pdflatex fair_clustering_survey
bibtex   fair_clustering_survey
pdflatex fair_clustering_survey
pdflatex fair_clustering_survey
\`\`\`

Requires a standard TeX Live / MiKTeX with \`newpxtext\`, \`fontawesome5\`, \`booktabs\`, \`tikz\`, \`natbib\`, \`hyperref\`.

## Files

| File | Provenance |
|---|---|
| \`fair_clustering_survey.tex\` | main document (preamble, abstract, provenance, \\input order) |
| \`intro.tex\` | **author-written** (your original, \`\\citep{XXX}\` placeholder flagged) |
| \`group-fair.tex\`, \`fair_rep_custer_img.tex\` | **author-written** (your originals, unchanged) |
| \`individual.tex\` | **author-written** (promoted from \`next.tex\`; \`NAME?\` stub removed) |
| \`ai-preliminaries.tex\` | **AI-drafted** |
| \`ai-proportionality.tex\` | **AI-drafted** |
| \`ai-techniques.tex\` | **AI-drafted** |
| \`ai-open.tex\` | **AI-drafted** |
| \`ai-results-table.tex\` | **AI-drafted** (Table 1) |
| \`*.bib\` | your three bibliographies |
| \`survey_ai_additions.bib\` | **AI-added** entries for keys missing from your bib (JungKL20, MahabadiV20, ChakrabartyN21, VakilianY22, ebbens2024subquadratic, ahmadi2022individual, chen2019proportionally, kleindessner2019guarantees) — verify before final use |

## AI disclosure
Every AI-drafted section begins with \`\\aibanner\` (defined in the preamble) and is listed in the provenance box after \`\\maketitle\`. To remove a banner once you've reviewed a section, delete its \`\\aibanner\` line. The web version shows the same disclosures.

## Notes
- The taxonomy figure (Fig. 2 in the web version) is currently web-only; add a TikZ version here if you want it in the PDF.
- \`individual.tex\` cites \`bateni2024scalable\` (in your bib) and the AI-added individual-fairness keys above.
