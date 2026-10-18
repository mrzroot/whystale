"""Filesystem helpers: project file listing (git-aware), mtimes, formatting."""

from __future__ import annotations

import fnmatch
import glob
import os
import re
import subprocess
import time
from typing import Dict, Iterable, List, Optional, Tuple

# Directories we never descend into when we have to walk the tree ourselves.
PRUNE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".next", ".nuxt", ".svelte-kit", ".turbo",
    ".output", "dist", "build", "out", "target", "coverage", ".idea", ".vscode",
    ".cache", ".gradle", "vendor", ".parcel-cache", ".yarn", ".pnpm-store",
    "site-packages", ".eggs",
}
# Always dropped from listings, even when git tracks them.
ALWAYS_SKIP = {".git", "node_modules"}

MAX_FILES = 200_000


class Project:
    """A scanned project directory with a cached file listing and stat cache."""

    def __init__(self, root: str, ignore_globs: Optional[List[str]] = None):
        self.root = os.path.abspath(root)
        self.ignore_globs = list(ignore_globs or [])
        self._stat: Dict[str, Optional[float]] = {}
        self.list_method = "walk"
        self.truncated = False
        self.files: List[str] = self._list_files()  # POSIX-style relative paths

    # -- paths -------------------------------------------------------------
    def abs(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/")) if rel else self.root

    def rel(self, path: str) -> str:
        r = os.path.relpath(path, self.root)
        return r.replace(os.sep, "/")

    def is_ignored(self, rel: str) -> bool:
        return any(path_glob_match(g, rel) for g in self.ignore_globs)

    # -- stat --------------------------------------------------------------
    def mtime(self, rel: str) -> Optional[float]:
        if rel in self._stat:
            return self._stat[rel]
        try:
            m: Optional[float] = os.stat(self.abs(rel)).st_mtime
        except OSError:
            m = None
        self._stat[rel] = m
        return m

    # -- listing -----------------------------------------------------------
    def _list_files(self) -> List[str]:
        files = self._git_files()
        if files is None:
            files = self._walk_files()
        else:
            self.list_method = "git"
        out = []
        for f in files:
            parts = f.split("/")
            if any(p in ALWAYS_SKIP for p in parts):
                continue
            if self.is_ignored(f):
                continue
            out.append(f)
            if len(out) >= MAX_FILES:
                self.truncated = True
                break
        return out

    def _git_files(self) -> Optional[List[str]]:
        try:
            p = subprocess.run(
                ["git", "-C", self.root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if p.returncode != 0:
            return None
        # `ls-files` also lists tracked files that were deleted from disk; drop those.
        res = []
        for item in p.stdout.split(b"\0"):
            if not item:
                continue
            rel = os.fsdecode(item)
            if os.path.lexists(os.path.join(self.root, rel)):
                res.append(rel)
        return res

    def _walk_files(self) -> List[str]:
        res: List[str] = []
        stack: List[Tuple[str, List["_Rule"]]] = [("", [])]
        while stack:
            rel_dir, rules = stack.pop()
            abs_dir = os.path.join(self.root, rel_dir) if rel_dir else self.root
            gi = os.path.join(abs_dir, ".gitignore")
            local = rules
            if os.path.isfile(gi):
                local = rules + parse_gitignore(gi, rel_dir)
            try:
                entries = sorted(os.scandir(abs_dir), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                rel = (rel_dir + "/" + e.name) if rel_dir else e.name
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if e.name in PRUNE_DIRS or ignored_by(local, rel, True):
                        continue
                    stack.append((rel, local))
                else:
                    if ignored_by(local, rel, False):
                        continue
                    res.append(rel)
                if len(res) >= MAX_FILES:
                    self.truncated = True
                    return res
        return res


# -- minimal .gitignore engine (fallback when git is unavailable) ------------
class _Rule:
    __slots__ = ("regex", "neg", "dir_only")

    def __init__(self, regex: "re.Pattern[str]", neg: bool, dir_only: bool):
        self.regex = regex
        self.neg = neg
        self.dir_only = dir_only


def _translate(pat: str) -> str:
    i, n, out = 0, len(pat), []
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 2)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pat[i + 1 : j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def parse_gitignore(path: str, rel_dir: str) -> List[_Rule]:
    rules: List[_Rule] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return rules
    base = re.escape(rel_dir + "/") if rel_dir else ""
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        if neg:
            line = line[1:]
        if line.startswith("\\"):
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line:
            continue
        anchored = "/" in line
        line = line.lstrip("/")
        body = _translate(line)
        prefix = "^" + base + ("" if anchored else "(?:.*/)?")
        rules.append(_Rule(re.compile(prefix + body + "$"), neg, dir_only))
    return rules


def ignored_by(rules: List[_Rule], rel: str, is_dir: bool) -> bool:
    verdict = False
    # a path is ignored if it, or any parent directory, matches (last match wins per path)
    parts = rel.split("/")
    for depth in range(1, len(parts) + 1):
        sub = "/".join(parts[:depth])
        sub_is_dir = depth < len(parts) or is_dir
        v = None
        for r in rules:
            if r.dir_only and not sub_is_dir:
                continue
            if r.regex.match(sub):
                v = not r.neg
        if v is True:
            return True
        if v is False:
            verdict = False
    return verdict


# -- globbing -----------------------------------------------------------------
def path_glob_match(pattern: str, rel: str) -> bool:
    """Match a POSIX relative path against a glob where ``**`` spans directories."""
    pattern = pattern.strip().lstrip("./").rstrip("/")
    if not pattern:
        return False
    prefix = "^" if "/" in pattern else "^(?:.*/)?"
    rx = prefix + _translate(pattern) + "(?:/.*)?$"
    return re.match(rx, rel) is not None


def expand_globs(root: str, patterns: Iterable[str], limit: int = 20000) -> List[str]:
    """Expand globs relative to ``root``; returns sorted relative POSIX paths."""
    found = set()
    for pat in patterns:
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            found.add(os.path.relpath(p, root).replace(os.sep, "/"))
            if len(found) >= limit:
                break
    return sorted(found)


# -- directory scans --------------------------------------------------------------
def newest_in_dir(path: str, cap: int = 30000, max_depth: int = 99) -> Tuple[Optional[float], Optional[str], int]:
    """Newest regular-file mtime below ``path`` -> (mtime, abs path, files seen)."""
    best: Optional[float] = None
    best_path: Optional[str] = None
    seen = 0
    stack = [(path, 0)]
    while stack and seen < cap:
        d, depth = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        stack.append((e.path, depth + 1))
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            seen += 1
            if best is None or st.st_mtime > best:
                best, best_path = st.st_mtime, e.path
            if seen >= cap:
                break
    return best, best_path, seen


def read_text(path: str, limit: int = 4_000_000) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return None


# -- formatting ---------------------------------------------------------------------
def fmt_time(ts: float, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    lt, ln = time.localtime(ts), time.localtime(now)
    if (lt.tm_year, lt.tm_yday) == (ln.tm_year, ln.tm_yday):
        return time.strftime("%H:%M:%S", lt)
    return time.strftime("%b %d %H:%M:%S", lt)


def fmt_delta(seconds: float) -> str:
    s = int(abs(seconds) + 0.5)
    if s < 60:
        return "%ds" % s
    m, s = divmod(s, 60)
    if m < 60:
        return "%dm %02ds" % (m, s)
    h, m = divmod(m, 60)
    if h < 48:
        return "%dh %02dm" % (h, m)
    d, h = divmod(h, 24)
    return "%dd %dh" % (d, h)


def iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def basename_match(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)
