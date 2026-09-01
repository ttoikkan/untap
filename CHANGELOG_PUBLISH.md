# Archive publisher changelog

## v79

- Introduces `untap_publish.py` as a standalone, standard-library-only local archive publisher.
- Reads only the machine-readable `untap-*` metadata contract embedded in v78+ HTML reports; it does not parse visible report content or understand matcher internals.
- Validates title, canonical ISO report date, non-negative summary counts, and the invariant `total = confirmed + needs review` before changing the archive.
- Derives permanent filenames as `YYYY-MM-DD-<safe-title-slug>.html` and refuses to overwrite an existing report.
- Validates all existing archived `.html` reports before adding a new one, then regenerates `index.html` deterministically with newest reports first.
- Escapes archive titles/metadata for HTML output and keeps report files self-contained.
- Performs local filesystem work only. It does not invoke Git, authenticate with GitHub, push commits, call GitHub APIs, or make network requests.
- Prints the explicit `git add`, descriptive `git commit`, and `git push` commands as next steps after a successful local publication.
