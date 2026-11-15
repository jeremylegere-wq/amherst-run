"""Release consistency tests: version format, changelog entry, release-notes extraction."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import release_notes  # noqa: E402
from game import __version__  # noqa: E402

SAMPLE = """# Changelog

## [Unreleased]

## [1.2.0] - 2030-01-02

### Added
- A thing.

## [1.1.0] - 2029-12-01
- Old thing.

[Unreleased]: https://example.invalid/compare
"""


class ReleaseTests(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(__version__, release_notes.SEMVER)

    def test_changelog_documents_the_current_version(self):
        with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(release_notes.changelog_section(text, __version__), "CHANGELOG.md needs a section for " + __version__)

    def test_section_extraction_stops_at_next_release(self):
        notes = release_notes.changelog_section(SAMPLE, "1.2.0")
        self.assertIn("A thing.", notes)
        self.assertNotIn("Old thing.", notes)
        self.assertIsNone(release_notes.changelog_section(SAMPLE, "9.9.9"))

    def test_last_section_stops_before_link_references(self):
        notes = release_notes.changelog_section(SAMPLE, "1.1.0")
        self.assertEqual(notes, "- Old thing.")

    def test_cli_rejects_mismatched_and_malformed_versions(self):
        self.assertEqual(release_notes.main(["x", "v" + __version__]), 0)
        self.assertEqual(release_notes.main(["x", "9.9.9"]), 1)
        self.assertEqual(release_notes.main(["x", "not-a-version"]), 1)
        self.assertEqual(release_notes.main(["x"]), 2)

    def test_launch_script_is_executable_shell_with_lf_endings(self):
        path = os.path.join(ROOT, "AmherstRun.sh")
        with open(path, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"#!/bin/bash"))
        self.assertNotIn(b"\r", data)


if __name__ == "__main__":
    unittest.main()
