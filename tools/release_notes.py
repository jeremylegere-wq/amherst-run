"""Check a release is consistent and print its notes.

    python tools/release_notes.py 0.1.0        # exit 0 and print the CHANGELOG section for 0.1.0
    python tools/release_notes.py v0.1.0       # a leading v (the git tag) is accepted

Fails (non-zero exit) unless:
  - the version is SemVer (1.2.3 or 1.2.3-rc.1),
  - it equals game.__version__ (the single source of truth),
  - CHANGELOG.md has a non-empty "## [version]" section.
Used by the release workflow and by anyone preparing a release locally.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")


def changelog_section(text, version):
    """Body of the '## [version]' section, or None if the heading is missing."""
    heading = re.compile(r"^## \[%s\]" % re.escape(version), re.M)
    m = heading.search(text)
    if not m:
        return None
    rest = text[m.end():]
    nl = rest.find("\n")
    rest = rest[nl + 1:] if nl >= 0 else ""
    nxt = re.search(r"^(## \[|\[[^\]]+\]: )", rest, re.M)      # next release heading or link references
    return (rest[:nxt.start()] if nxt else rest).strip()


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    version = argv[1][1:] if argv[1].startswith("v") else argv[1]
    if not SEMVER.match(version):
        print("error: %r is not a SemVer version like 1.2.3 or 1.2.3-rc.1" % version, file=sys.stderr)
        return 1
    from game import __version__
    if version != __version__:
        print("error: tag/version %s does not match game.__version__ = %s (edit game/__init__.py)"
              % (version, __version__), file=sys.stderr)
        return 1
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        notes = changelog_section(f.read(), version)
    if not notes:
        print("error: CHANGELOG.md has no non-empty '## [%s]' section" % version, file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
