# Archive publisher changelog

## v86

- Uses validated optional ambiguous/failed counts in archive summaries; residual statuses remain unresolved.
- Accepts legacy metadata unchanged and labels its non-confirmed aggregate unresolved rather than guessing a breakdown.
- Rejects partial, negative, or inconsistent optional status counts before archive mutation.

## v85

- Labels unresolved results as `ambiguous` in visible archive-card summaries instead of `need review`.
- Keeps the `untap-review-count` metadata contract, validation, ordering, replacement safety, and filesystem behavior unchanged.

## v84

- Harmonizes the generated archive index with the HTML reports' adaptive light/dark palette, responsive 900px content width, typography, link treatment, borders, rounded cards, and spacing rhythm.
- Keeps the index fully self-contained and JavaScript-free, with publication ordering, metadata validation, replacement safety, and filesystem behavior unchanged.

## v81

- Adds optional `--replace` for explicitly replacing a regenerated report with the same normalized descriptive-title identity, even when its generation date has changed.
- Keeps accidental-replacement protection unchanged by default: without `--replace`, an existing logical title still fails closed.
- Replacement validates the new source and every existing archived report before mutation, preserves the existing archive filename/public URL, and regenerates the index with exactly one entry for the logical report.
- Uses atomic destination writes and restores the previous report if the subsequent index update fails.
- Multiple existing normalized-title matches fail closed, and a filename collision belonging to a different title is never overwritten by `--replace`.
- If `--replace` is supplied when no logical-title match exists, publication proceeds normally.
- Successful replacement output is labeled `Replaced locally` and suggests a descriptive `Replace ...` Git commit; Git itself remains external and explicit.
- No GitHub, network, matcher, parser, report-rendering, or transport responsibility is added.

## v79

- Introduces `untap_publish.py` as a standalone, standard-library-only local archive publisher.
- Reads only the machine-readable `untap-*` metadata contract embedded in v78+ HTML reports; it does not parse visible report content or understand matcher internals.
- Validates title, canonical ISO report date, non-negative summary counts, and the invariant `total = confirmed + needs review` before changing the archive.
- Derives permanent filenames as `YYYY-MM-DD-<safe-title-slug>.html` and refuses to overwrite an existing report.
- Validates all existing archived `.html` reports before adding a new one, then regenerates `index.html` deterministically with newest reports first.
- Escapes archive titles/metadata for HTML output and keeps report files self-contained.
- Performs local filesystem work only. It does not invoke Git, authenticate with GitHub, push commits, call GitHub APIs, or make network requests.
- Prints the explicit `git add`, descriptive `git commit`, and `git push` commands as next steps after a successful local publication.
