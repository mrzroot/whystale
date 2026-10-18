"""Stale build output: sources newer than dist/ build/ out/ .next/ target/ ..."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from . import knowledge as K
from .config import Config
from .fsutil import Project, fmt_delta, fmt_time, iso, newest_in_dir
from .model import ARTIFACT, STALE, Finding
from .pkgutil import detect_pm, scripts_of

NON_BUILD_NAME_PREFIXES = (
    ".eslintrc", "eslint.config.", "jest.config.", "vitest.config.", ".prettierrc", "prettier.config.",
    "cypress.config.", "playwright.config.", "commitlint.config.", "stylelint.config.", ".stylelintrc",
    "karma.conf.", "lint-staged.config.", "vitest.workspace.",
)
JS_OUTPUT_EXTS = (".js", ".mjs", ".cjs", ".css", ".html", ".map")


def _is_source(rel_in_pkg: str) -> bool:
    parts = rel_in_pkg.split("/")
    name = parts[-1]
    low = name.lower()
    if any(p in K.TEST_DIR_NAMES or p in (".github", "docs") for p in parts[:-1]):
        return False
    if K.TEST_NAME_RE.search(low) or low.endswith(".d.ts"):
        return False
    if name.startswith(NON_BUILD_NAME_PREFIXES):
        return False
    ext = os.path.splitext(low)[1]
    if len(parts) > 1 and parts[0] in K.ASSET_DIRS and ext in K.ASSET_EXTS:
        return True
    if ext in K.SOURCE_EXTS:
        return True
    if ext in K.DATA_EXT_DIRS and len(parts) > 1 and parts[0] in K.DATA_EXT_DIRS[ext]:
        return True
    return False


def _looks_like_js_build(path: str) -> bool:
    seen = 0
    stack = [(path, 0)]
    while stack and seen < 400:
        d, depth = stack.pop()
        try:
            for e in os.scandir(d):
                seen += 1
                if e.is_dir(follow_symlinks=False):
                    if depth < 3:
                        stack.append((e.path, depth + 1))
                elif e.name.lower().endswith(JS_OUTPUT_EXTS):
                    return True
        except OSError:
            continue
    return False


def _nearest_dir(rel: str, dirs: set) -> Optional[str]:
    cur = rel.rsplit("/", 1)[0] if "/" in rel else ""
    while True:
        if cur in dirs:
            return cur
        if not cur:
            return None
        cur = cur.rsplit("/", 1)[0] if "/" in cur else ""


def _newer_sources(project: Project, rels: List[str], limit_m: float, grace: float) -> List[Tuple[float, str]]:
    res = []
    for rel in rels:
        m = project.mtime(rel)
        if m is not None and m > limit_m + grace:
            res.append((m, rel))
    res.sort(reverse=True)
    return res


def _finding(project: Project, key: str, subject: str, art_rel: str, art_m: float, newer: List[Tuple[float, str]],
             total: int, fix: List[str], notes: List[str], now: float) -> Finding:
    top = newer[:3]
    reason = "%s was last written %s; %d source file(s) changed after that (newest %s later)" % (
        art_rel, fmt_time(art_m, now), len(newer), fmt_delta(top[0][0] - art_m))
    return Finding(
        kind=ARTIFACT, level=STALE, key=key, subject=subject, reason=reason, evidence="mtime", fix=fix,
        older_than=[{"path": r, "what": "source", "changed": iso(m), "seconds_after_build": round(m - art_m, 1)} for m, r in top],
        notes=notes,
        details={"output": art_rel, "output_written": iso(art_m), "newer_source_files": len(newer), "sources_considered": total},
    )


def check_artifacts(project: Project, cfg: Config, now: float) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    ignored: List[dict] = []
    files = project.files
    pkg_dirs = {f.rsplit("/", 1)[0] if "/" in f else "" for f in files if f.rsplit("/", 1)[-1] == "package.json"}
    # --- node ---------------------------------------------------------------
    by_pkg: Dict[str, List[str]] = {d: [] for d in pkg_dirs}
    for f in files:
        d = _nearest_dir(f, pkg_dirs)
        if d is not None:
            by_pkg[d].append(f)
    for d in sorted(pkg_dirs):
        prefix = d + "/" if d else ""
        outs = [o for o in K.NODE_OUTPUT_DIRS if os.path.isdir(project.abs(prefix + o))]
        if not outs:
            continue
        sources: List[str] = []
        for f in by_pkg[d]:
            inner = f[len(prefix):]
            if inner.split("/", 1)[0] in K.NODE_OUTPUT_DIRS:
                continue
            if _is_source(inner):
                sources.append(f)
        if not sources:
            continue
        scripts = scripts_of(project, d)
        pm = detect_pm(project, d)
        for o in outs:
            out_rel = prefix + o
            if o in ("dist", "build", "out") and not _looks_like_js_build(project.abs(out_rel)):
                continue
            art_m, _, seen = newest_in_dir(project.abs(out_rel))
            if art_m is None:
                continue
            newer = _newer_sources(project, sources, art_m, cfg.fs_grace_seconds)
            if not newer:
                continue
            if "build" in scripts:
                cmd = K.pm_run(pm, "build")
                fix = [(cmd if not d else "cd %s && %s" % (d, cmd))]
                notes = []
            else:
                fix = ["# no \"build\" script in %spackage.json: run your usual build command" % prefix]
                notes = ["whystale could not infer the build command"]
            findings.append(_finding(project, "artifact:" + out_rel, "%s is older than its sources" % out_rel, out_rel,
                                     art_m, newer, len(sources), fix, notes, now))
    # --- rust ---------------------------------------------------------------
    cargo_dirs = sorted({f.rsplit("/", 1)[0] if "/" in f else "" for f in files if f.rsplit("/", 1)[-1] == "Cargo.toml"})
    for d in cargo_dirs:
        prefix = d + "/" if d else ""
        target = prefix + "target"
        if not os.path.isdir(project.abs(target)):
            continue
        best: Optional[Tuple[float, str]] = None
        for prof in ("debug", "release"):
            pdir = project.abs(target + "/" + prof)
            try:
                entries = list(os.scandir(pdir))
            except OSError:
                continue
            m = None
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False) or e.name.endswith(".d") or e.name == ".cargo-lock":
                        continue
                    t = e.stat().st_mtime
                except OSError:
                    continue
                m = t if m is None or t > m else m
            if m is not None and (best is None or m > best[0]):
                best = (m, prof)
        if best is None:
            continue
        sources = [f for f in files if f.startswith(prefix) and not f.startswith(target + "/")
                   and (f.endswith(".rs") or f.rsplit("/", 1)[-1] in ("Cargo.toml", "Cargo.lock", "build.rs"))]
        newer = _newer_sources(project, sources, best[0], cfg.fs_grace_seconds)
        if not newer:
            continue
        cmd = "cargo build" + (" --release" if best[1] == "release" else "")
        fix = [cmd if not d else "cd %s && %s" % (d, cmd)]
        findings.append(_finding(project, "artifact:" + target, "%s/%s is older than its sources" % (target, best[1]),
                                 "%s/%s" % (target, best[1]), best[0], newer, len(sources), fix,
                                 ["only the most recently built profile is checked"], now))
    return findings, ignored
