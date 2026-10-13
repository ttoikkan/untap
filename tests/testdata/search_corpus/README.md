# Search replay corpus

These are hand-authored, sanitized payload-shaped fixtures, not live captures. They exercise the real search flow by replacing only the Playwright page. `tests/replay_page.py` supplies UI bootstrap events and direct fetch responses. No matcher, request-builder, parser or fallback helper is patched.

Each JSON case declares search arguments, an ordered list of exchanges, expected result fields and excluded inspection URLs. An exchange specifies UI or fetch transport and every index/parameter in the POST body, plus the status and minimal Algolia response. Unexpected requests, wrong parameters, unused exchanges, unintended navigation and leaked listeners fail even if production exception handling catches the original replay error. Transport authority state resets for each case.

S1 pins conflicting beer-only inspection links. S7 uses real scores and a stricter threshold to pin retention of a weak compatible primary candidate: a stronger conflicting fallback must not replace it. Other cases cover winning-fallback metadata, page-zero reuse/conditional expansion, an unusable zero-hit page, and immediate 429 termination at bootstrap, fallback and expansion.

To add a recording, remove headers, keys, cookies and unrelated hit fields. Retain request query/page/index/parameters and only fields consumed by response validation, candidate construction and matching. Declare actual capture provenance; hand-authored rare-condition cases must say so. Do not copy whole third-party responses into the repository.

Run `python3 -B -m unittest tests.test_untap_corpus`. The passive smoke shape canary uses `algolia_response_shape_issues` in `untap.transport`; corpus tests keep its required-field expectations aligned. Optional additions are allowed, and intentional missing metadata is annotated with `shape_issues`.
