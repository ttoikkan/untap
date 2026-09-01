import contextlib
import io
import tempfile
import unittest
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
        self.assertIn("September 1, 2026 · 5 beers · 4 confirmed · 1 need review", html)
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

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "results.html"
            source.write_text(_report_html(), encoding="utf-8")
            archive = self._archive(root)
            destination = archive / "reports" / "2026-09-01-pien-new-arrivals-september-2026.html"
            destination.write_text("keep me", encoding="utf-8")

            with self.assertRaisesRegex(untap_publish.PublishError, "refusing to overwrite"):
                untap_publish.publish_report(source, archive)
            self.assertEqual(destination.read_text(encoding="utf-8"), "keep me")
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
