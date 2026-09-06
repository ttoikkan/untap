"""Offline tests for the read-only Algolia inspection tool."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import untap_inspect


class InspectionFormattingTests(unittest.TestCase):
    def test_inventory_preserves_presence_types_and_raw_samples(self):
        inspections = [{"hits": [
            {"in_production": True, "alias_alt": ["Old Name"]},
            {"in_production": 0, "spelling_alt": None},
            {"beer_name": "Beer"},
        ]}]
        inventory = {item["field"]: item for item in untap_inspect.field_inventory(inspections)}
        self.assertEqual(inventory["in_production"]["present"], 2)
        self.assertEqual(inventory["in_production"]["hits"], 3)
        self.assertEqual(inventory["in_production"]["types"], ["boolean", "number"])
        self.assertEqual(inventory["alias_alt"]["samples"], ['["Old Name"]'])
        self.assertEqual(inventory["spelling_alt"]["types"], ["null"])

    def test_summary_highlights_interesting_values_and_all_field_names(self):
        inspections = [{
            "query": "Brewery Beer", "transport": "ui-bootstrap", "error": None,
            "nbHits": 1, "nbPages": 1,
            "hits": [{"beer_name": "Beer", "brewery_name": "Brewery",
                      "in_production": 0, "alias_alt": ["Beer Alias"],
                      "unfamiliar_field": {"nested": True}}],
        }]
        summary = untap_inspect.render_summary(inspections)
        self.assertTrue(summary.startswith("Untappd Algolia inspection\n"))
        self.assertIn("in_production [number]: 0", summary)
        self.assertIn('alias_alt [array]: ["Beer Alias"]', summary)
        self.assertIn("unfamiliar_field: 1/1 hits", summary)
        self.assertIn('sample: {"nested": true}', summary)


class InspectionTransportTests(unittest.TestCase):
    def test_inspect_query_returns_unmodified_page_zero_hits(self):
        hit = {"beer_name": "Beer", "unknown": [1, {"x": False}]}
        transport = {"events": [object()], "transport": "browser-fetch", "error": None}
        page_zero = {"nbHits": 7, "nbPages": 2, "hitsPerPage": 5, "hits": [hit]}
        with mock.patch.object(untap_inspect, "_run_page0_search_transport",
                               return_value=transport), \
             mock.patch.object(untap_inspect, "_matching_algolia_initial_page",
                               return_value=page_zero):
            result = untap_inspect.inspect_query(object(), "Brewery Beer")
        self.assertIs(result["hits"][0], hit)
        self.assertEqual(result["nbHits"], 7)
        self.assertEqual(result["transport"], "browser-fetch")

    def test_all_pages_are_fetched_serially_and_preserve_raw_hits(self):
        request = {"algolia_requests": [{"query": "Beer", "indexName": "beer"}]}
        transport = {"events": [object()], "request_event": request,
                     "transport": "ui-bootstrap", "error": None}
        page_zero = {"nbHits": 3, "nbPages": 3, "hitsPerPage": 1,
                     "hits": [{"objectID": "0"}]}
        pages = [
            ({"results": [{"index": "beer", "page": 1, "nbHits": 3,
                            "nbPages": 3, "hitsPerPage": 1,
                            "hits": [{"objectID": "1", "alias_alt": ["alias"]}]}]}, None),
            ({"results": [{"index": "beer", "page": 2, "nbHits": 3,
                            "nbPages": 3, "hitsPerPage": 1,
                            "hits": [{"objectID": "2"}]}]}, None),
        ]
        with mock.patch.object(untap_inspect, "_run_page0_search_transport",
                               return_value=transport), \
             mock.patch.object(untap_inspect, "_matching_algolia_initial_page",
                               return_value=page_zero), \
             mock.patch.object(untap_inspect, "_fetch_algolia_page",
                               side_effect=pages) as fetch:
            result = untap_inspect.inspect_query(object(), "Beer", all_pages=True)
        self.assertEqual([hit["objectID"] for hit in result["hits"]], ["0", "1", "2"])
        self.assertEqual(result["pages_inspected"], 3)
        self.assertFalse(result["capped"])
        self.assertEqual([call.args[2] for call in fetch.call_args_list], [1, 2])

    def test_default_inspection_never_fetches_additional_pages(self):
        transport = {"events": [object()], "request_event": {},
                     "transport": "ui-bootstrap", "error": None}
        page_zero = {"nbHits": 35, "nbPages": 7, "hitsPerPage": 5, "hits": [{}]}
        with mock.patch.object(untap_inspect, "_run_page0_search_transport",
                               return_value=transport), \
             mock.patch.object(untap_inspect, "_matching_algolia_initial_page",
                               return_value=page_zero), \
             mock.patch.object(untap_inspect, "_fetch_algolia_page") as fetch:
            result = untap_inspect.inspect_query(object(), "Beer")
        fetch.assert_not_called()
        self.assertEqual(result["pages_inspected"], 1)

    def test_http_429_is_reported_when_page_cannot_be_validated(self):
        transport = {"events": [{"kind": "response", "status": 429}],
                     "transport": "browser-fetch", "error": None}
        with mock.patch.object(untap_inspect, "_run_page0_search_transport",
                               return_value=transport), \
             mock.patch.object(untap_inspect, "_matching_algolia_initial_page",
                               return_value=None):
            result = untap_inspect.inspect_query(object(), "Beer")
        self.assertEqual(result["error"], "Algolia response HTTP 429")


class InspectionCliTests(unittest.TestCase):
    def test_query_run_writes_summary_and_raw_json_without_matching(self):
        item = {"query": "Brewery Beer", "transport": "ui-bootstrap", "error": None,
                "nbHits": 1, "nbPages": 1, "hitsPerPage": 5,
                "hits": [{"beer_name": "Beer", "in_production": True}]}
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                with mock.patch.object(untap_inspect, "untappd_browser_page",
                                       return_value=contextlib.nullcontext(object())), \
                     mock.patch.object(untap_inspect, "inspect_query", return_value=item), \
                     contextlib.redirect_stdout(io.StringIO()):
                    code = untap_inspect.main(["--query", "Brewery Beer"])
                self.assertEqual(code, 0)
                folders = list(Path("inspections").iterdir())
                self.assertEqual(len(folders), 1)
                payload = json.loads((folders[0] / "hits.json").read_text())
                self.assertEqual(payload["format"], "untap-algolia-inspection-v1")
                self.assertEqual(payload["queries"][0]["hits"], item["hits"])
                self.assertIn("Field inventory", (folders[0] / "summary.txt").read_text())
            finally:
                os.chdir(previous)

    def test_empty_file_fails_before_browser_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "empty.txt"
            source.write_text("\n", encoding="utf-8")
            with mock.patch.object(untap_inspect, "untappd_browser_page") as browser, \
                 contextlib.redirect_stderr(io.StringIO()):
                code = untap_inspect.main(["--file", str(source)])
            self.assertEqual(code, 2)
            browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
