import contextlib
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import untap_publish


def _report_html(
    title="Pien New Arrivals - September 2026",
    report_date="2026-09-01",
    total="31",
    confirmed="29",
    review="2",
):
    return f"""<!doctype html>
<html><head>
<meta name="untap-report-title" content="{title}">
<meta name="untap-report-date" content="{report_date}">
<meta name="untap-total-beers" content="{total}">
<meta name="untap-confirmed-count" content="{confirmed}">
<meta name="untap-review-count" content="{review}">
<title>{title}</title>
</head><body></body></html>
"""


class PublishMetadataTests(unittest.TestCase):
    def test_reads_v78_metadata_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.html"
            path.write_text(_report_html(), encoding="utf-8")
            metadata = untap_publish.read_report_metadata(path)
        self.assertEqual(metadata.title, "Pien New Arrivals - September 2026")
        self.assertEqual(metadata.report_date, "2026-09-01")
        self.assertEqual(metadata.total_beers, 31)
        self.assertEqual(metadata.confirmed_count, 29)
        self.assertEqual(metadata.review_count, 2)

    def test_missing_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.html"
            path.write_text("<html><head><title>Not Untap</title></head></html>", encoding="utf-8")
            with self.assertRaisesRegex(untap_publish.PublishError, "missing Untap report metadata"):
                untap_publish.read_report_metadata(path)

    def test_invalid_date_and_inconsistent_counts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.html"
            path.write_text(_report_html(report_date="01-09-2026"), encoding="utf-8")
            with self.assertRaisesRegex(untap_publish.PublishError, "untap-report-date"):
                untap_publish.read_report_metadata(path)
            path.write_text(_report_html(total="31", confirmed="30", review="2"), encoding="utf-8")
            with self.assertRaisesRegex(untap_publish.PublishError, "inconsistent report counts"):
                untap_publish.read_report_metadata(path)

    def test_duplicate_metadata_field_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.html"
            html = _report_html().replace(
                '<meta name="untap-report-date" content="2026-09-01">',
                '<meta name="untap-report-date" content="2026-09-01">\n'
                '<meta name="untap-report-date" content="2026-09-02">',
            )
            path.write_text(html, encoding="utf-8")
            with self.assertRaisesRegex(untap_publish.PublishError, "duplicate report metadata"):
                untap_publish.read_report_metadata(path)

    def test_slug_is_url_safe_and_bounded_to_title_content(self):
        self.assertEqual(
            untap_publish.slugify_title("Pien New Arrivals - Sëptember 2026!"),
            "pien-new-arrivals-september-2026",
        )
        self.assertEqual(untap_publish.slugify_title("東京"), "report")


class ArchiveRenderingTests(unittest.TestCase):
    def test_index_is_newest_first_and_escapes_titles(self):
        old = untap_publish.ArchiveReport(
            untap_publish.ReportMetadata("Older & Good", "2026-08-01", 4, 4, 0),
            "2026-08-01-older-good.html",
        )
        new = untap_publish.ArchiveReport(
            untap_publish.ReportMetadata('<Newest "Report">', "2026-09-01", 5, 4, 1),
            "2026-09-01-newest-report.html",
        )
        html = untap_publish.render_archive_index([old, new])
        self.assertLess(html.index("&lt;Newest &quot;Report&quot;&gt;"), html.index("Older &amp; Good"))
        self.assertIn("September 1, 2026 · 5 beers · 4 confirmed · 1 unresolved", html)
        self.assertIn('href="reports/2026-09-01-newest-report.html"', html)

    def test_index_tie_order_is_deterministic(self):
        first = untap_publish.ArchiveReport(
            untap_publish.ReportMetadata("Alpha", "2026-09-01", 1, 1, 0), "alpha.html"
        )
        second = untap_publish.ArchiveReport(
            untap_publish.ReportMetadata("Beta", "2026-09-01", 1, 1, 0), "beta.html"
        )
        one = untap_publish.render_archive_index([first, second])
        two = untap_publish.render_archive_index([second, first])
        self.assertEqual(one, two)

    def test_index_uses_report_visual_language(self):
        html = untap_publish.render_archive_index([])
        self.assertIn(":root { color-scheme: light dark;", html)
        self.assertIn("main { width: min(900px, 100%);", html)
        self.assertIn('class="report-list"', html)
        self.assertIn("border-radius: 14px", html)
        self.assertIn("color: LinkText", html)
        self.assertIn("@media (max-width: 520px)", html)


class PublishFilesystemTests(unittest.TestCase):
    def _archive(self, root: Path) -> Path:
        archive = root / "untap-results"
        (archive / "reports").mkdir(parents=True)
        (archive / "index.html").write_text("old index", encoding="utf-8")
        return archive

    def test_publish_copies_report_and_regenerates_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(), encoding="utf-8")
            archive = self._archive(root)

            published = untap_publish.publish_report(source, archive)
            destination = archive / "reports" / published.filename

            self.assertEqual(
                published.filename,
                "2026-09-01-pien-new-arrivals-september-2026.html",
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            index = (archive / "index.html").read_text(encoding="utf-8")
            self.assertIn("Pien New Arrivals - September 2026", index)
            self.assertIn(published.filename, index)

    def test_existing_logical_report_is_never_replaced_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(report_date="2026-09-02"), encoding="utf-8")
            archive = self._archive(root)
            destination = archive / "reports" / "2026-09-01-pien-new-arrivals-september-2026.html"
            old_report = _report_html(report_date="2026-09-01").replace(
                "</body>", "<p>keep me</p></body>"
            )
            destination.write_text(old_report, encoding="utf-8")

            with self.assertRaisesRegex(
                untap_publish.PublishError, "refusing to replace existing logical report"
            ):
                untap_publish.publish_report(source, archive)
            self.assertEqual(destination.read_text(encoding="utf-8"), old_report)
            self.assertFalse(
                (archive / "reports" / "2026-09-02-pien-new-arrivals-september-2026.html").exists()
            )
            self.assertEqual((archive / "index.html").read_text(encoding="utf-8"), "old index")

    def test_replace_matches_title_across_generation_dates_and_preserves_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(
                _report_html(report_date="2026-09-02").replace(
                    "</body>", "<p>v81 replacement</p></body>"
                ),
                encoding="utf-8",
            )
            archive = self._archive(root)
            destination = archive / "reports" / "2026-09-01-pien-new-arrivals-september-2026.html"
            destination.write_text(
                _report_html(report_date="2026-09-01").replace(
                    "</body>", "<p>old report</p></body>"
                ),
                encoding="utf-8",
            )

            published = untap_publish.publish_report(source, archive, replace=True)

            self.assertEqual(published.filename, destination.name)
            self.assertEqual(published.metadata.report_date, "2026-09-02")
            self.assertIn("v81 replacement", destination.read_text(encoding="utf-8"))
            self.assertNotIn("old report", destination.read_text(encoding="utf-8"))
            self.assertFalse(
                (archive / "reports" / "2026-09-02-pien-new-arrivals-september-2026.html").exists()
            )
            index = (archive / "index.html").read_text(encoding="utf-8")
            self.assertEqual(index.count("Pien New Arrivals - September 2026"), 1)
            self.assertEqual(index.count(destination.name), 1)
            self.assertIn("September 2, 2026", index)

    def test_replace_preserves_existing_report_if_index_update_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html().replace("</body>", "<p>replacement</p></body>"), encoding="utf-8")
            archive = self._archive(root)
            destination = archive / "reports" / "2026-09-01-pien-new-arrivals-september-2026.html"
            old_report = _report_html().replace("</body>", "<p>keep old</p></body>")
            destination.write_text(old_report, encoding="utf-8")

            with mock.patch.object(untap_publish, "_atomic_write_text", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    untap_publish.publish_report(source, archive, replace=True)

            self.assertEqual(destination.read_text(encoding="utf-8"), old_report)
            self.assertEqual((archive / "index.html").read_text(encoding="utf-8"), "old index")

    def test_replace_flag_on_new_identity_publishes_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(title="Brand New Report"), encoding="utf-8")
            archive = self._archive(root)

            published = untap_publish.publish_report(source, archive, replace=True)

            self.assertTrue((archive / "reports" / published.filename).is_file())
            self.assertIn("Brand New Report", (archive / "index.html").read_text(encoding="utf-8"))

    def test_logical_identity_normalizes_case_and_whitespace_only(self):
        self.assertEqual(
            untap_publish._report_identity("  Pien   New Arrivals  "),
            untap_publish._report_identity("pien new arrivals"),
        )
        self.assertNotEqual(
            untap_publish._report_identity("Café"),
            untap_publish._report_identity("Cafe"),
        )

    def test_slug_collision_never_allows_replacing_different_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(
                _report_html(title="Cafe", report_date="2026-09-01"),
                encoding="utf-8",
            )
            archive = self._archive(root)
            destination = archive / "reports" / "2026-09-01-cafe.html"
            destination.write_text(
                _report_html(title="Café", report_date="2026-09-01"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                untap_publish.PublishError, "filename belonging to another report"
            ):
                untap_publish.publish_report(source, archive, replace=True)

            self.assertIn("Café", destination.read_text(encoding="utf-8"))
            self.assertEqual((archive / "index.html").read_text(encoding="utf-8"), "old index")

    def test_duplicate_logical_titles_in_archive_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(
                _report_html(report_date="2026-09-03"),
                encoding="utf-8",
            )
            archive = self._archive(root)
            reports = archive / "reports"
            (reports / "first.html").write_text(
                _report_html(report_date="2026-09-01"), encoding="utf-8"
            )
            (reports / "second.html").write_text(
                _report_html(title="  pien  new arrivals - september 2026  ", report_date="2026-09-02"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                untap_publish.PublishError, "multiple reports with the same logical title"
            ):
                untap_publish.publish_report(source, archive, replace=True)

            self.assertEqual((archive / "index.html").read_text(encoding="utf-8"), "old index")

    def test_malformed_existing_archive_report_prevents_all_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(), encoding="utf-8")
            archive = self._archive(root)
            (archive / "reports" / "broken.html").write_text("<html>broken</html>", encoding="utf-8")

            with self.assertRaisesRegex(untap_publish.PublishError, "missing Untap report metadata"):
                untap_publish.publish_report(source, archive)
            self.assertFalse(
                (archive / "reports" / "2026-09-01-pien-new-arrivals-september-2026.html").exists()
            )
            self.assertEqual((archive / "index.html").read_text(encoding="utf-8"), "old index")

    def test_archive_requires_existing_reports_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(), encoding="utf-8")
            archive = root / "untap-results"
            archive.mkdir()
            with self.assertRaisesRegex(untap_publish.PublishError, "reports directory does not exist"):
                untap_publish.publish_report(source, archive)

    def test_cli_prints_local_git_next_steps_but_performs_no_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(), encoding="utf-8")
            archive = self._archive(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = untap_publish.main([str(source), str(archive)])
            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Published locally:", output)
            self.assertIn("git add .", output)
            self.assertIn("git commit -m 'Publish Pien New Arrivals - September 2026'", output)
            self.assertIn("git push", output)

    def test_cli_replace_reports_replacement_across_dates_but_default_still_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(
                _report_html(report_date="2026-09-02").replace(
                    "</body>", "<p>new</p></body>"
                ),
                encoding="utf-8",
            )
            archive = self._archive(root)
            destination = archive / "reports" / "2026-09-01-pien-new-arrivals-september-2026.html"
            destination.write_text(_report_html(report_date="2026-09-01"), encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = untap_publish.main([str(source), str(archive)])
            self.assertEqual(exit_code, 2)
            self.assertIn("refusing to replace existing logical report", stderr.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = untap_publish.main([str(source), str(archive), "--replace"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Replaced locally:", stdout.getvalue())
            self.assertIn("reports/2026-09-01-pien-new-arrivals-september-2026.html", stdout.getvalue())
            self.assertIn("git commit -m 'Replace Pien New Arrivals - September 2026'", stdout.getvalue())
            self.assertIn("<p>new</p>", destination.read_text(encoding="utf-8"))
            self.assertFalse(
                (archive / "reports" / "2026-09-02-pien-new-arrivals-september-2026.html").exists()
            )

    def test_cli_shell_quotes_descriptive_commit_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(title="Tapper's Choice"), encoding="utf-8")
            archive = self._archive(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = untap_publish.main([str(source), str(archive)])
            self.assertEqual(exit_code, 0)
            self.assertIn("git commit -m 'Publish Tapper'", stdout.getvalue())
            self.assertIn("'\"'\"'s Choice'", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
