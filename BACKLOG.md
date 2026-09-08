# Backlog

## Manual Untappd URL override

Allow a user to supply an Untappd beer URL when the correct beer is absent
from the report's candidates, particularly for failed searches or translated
menu names. This is a planned feature, not implemented.

- Prefer a browser-led review workflow: show the retrieved beer details before
  explicit manual confirmation.
- Validate the URL and beer identity; surface brewery and ABV discrepancies
  rather than treating the URL as an automatic match.
- Preserve the original menu input, original result, and manual decision in
  the snapshot. Support selection export/application and later changes.
- Keep automatic matching and scoring unchanged. Determine how retrieval fits
  the static published-report and local CLI workflow during design.

Motivating case: the menu lists EMPORIUM X LA FOSSE X JACKALHOP / RICE LAGER /
4.5%, while Untappd lists LAGER DE RIZ by Emporium Microbrasserie, beer ID
6684380. The user supplied a screenshot confirming all three collaborators
and 4.5% ABV. Algolia finds the French name but has empty alias_alt and
spelling_alt arrays.
