import os
import shutil
import subprocess

import pytest

from whystale.fsutil import (Project, fmt_delta, ignored_by, parse_gitignore, path_glob_match)
from helpers import mk


def _ig(tmp_path, text, rel, is_dir=False):
    p = tmp_path / ".gitignore"
    p.write_text(text)
    return ignored_by(parse_gitignore(str(p), ""), rel, is_dir)


@pytest.mark.parametrize("pattern,rel,is_dir,expected", [
    ("*.log", "a.log", False, True),
    ("*.log", "sub/a.log", False, True),
    ("*.log", "a.txt", False, False),
    ("/dist", "dist", True, True),
    ("/dist", "sub/dist", True, False),
    ("build/", "build", True, True),
    ("build/", "build", False, False),
    ("**/gen", "a/b/gen", True, True),
    ("foo/*.js", "foo/x.js", False, True),
    ("foo/*.js", "foo/sub/x.js", False, False),
    ("node_modules", "node_modules/pkg/index.js", False, True),
])
def test_gitignore_patterns(tmp_path, pattern, rel, is_dir, expected):
    assert _ig(tmp_path, pattern + "\n", rel, is_dir) is expected


def test_gitignore_negation(tmp_path):
    text = "*.log\n!keep.log\n"
    assert _ig(tmp_path, text, "a.log") is True
    assert _ig(tmp_path, text, "keep.log") is False


def test_walk_listing_respects_gitignore_and_prunes(tmp_path):
    mk(tmp_path, ".gitignore", "secret.txt\nlogs/\n")
    mk(tmp_path, "src/a.js")
    mk(tmp_path, "secret.txt")
    mk(tmp_path, "logs/x.log")
    mk(tmp_path, "node_modules/pkg/index.js")
    mk(tmp_path, "nested/.gitignore", "*.tmp\n")
    mk(tmp_path, "nested/keep.js")
    mk(tmp_path, "nested/drop.tmp")
    mk(tmp_path, "top.tmp")
    files = set(Project(str(tmp_path)).files)
    assert {"src/a.js", "nested/keep.js", "top.tmp", ".gitignore"} <= files
    assert "secret.txt" not in files and "logs/x.log" not in files
    assert "nested/drop.tmp" not in files
    assert not any(f.startswith("node_modules") for f in files)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_listing_matches_git(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    mk(tmp_path, ".gitignore", "ignored.txt\n")
    mk(tmp_path, "tracked.js")
    mk(tmp_path, "ignored.txt")
    mk(tmp_path, "untracked.js")
    subprocess.run(["git", "add", "tracked.js"], cwd=tmp_path, check=True)
    p = Project(str(tmp_path))
    assert p.list_method == "git"
    assert set(p.files) == {".gitignore", "tracked.js", "untracked.js"}
    os.remove(tmp_path / "tracked.js")  # deleted-but-tracked must not be listed
    assert "tracked.js" not in Project(str(tmp_path)).files


def test_user_ignore_globs(tmp_path):
    mk(tmp_path, "a/keep.js")
    mk(tmp_path, "a/legacy/old.js")
    mk(tmp_path, "x.min.js")
    p = Project(str(tmp_path), ["a/legacy/**", "*.min.js"])
    assert p.files == ["a/keep.js"]


def test_path_glob_match():
    assert path_glob_match("dist/**", "dist/a/b.js")
    assert path_glob_match("*.md", "docs/readme.md")
    assert not path_glob_match("docs/*.md", "other/readme.md")


def test_fmt_delta():
    assert fmt_delta(5) == "5s"
    assert fmt_delta(125) == "2m 05s"
    assert fmt_delta(3 * 3600 + 60) == "3h 01m"
    assert fmt_delta(3 * 86400) == "3d 0h"
