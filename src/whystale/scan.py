"""Orchestration: run every enabled check and assemble a Report."""

from __future__ import annotations

import time
from typing import Optional

from .checks_artifacts import check_artifacts
from .checks_deps import check_deps
from .checks_generated import check_generated
from .checks_process import check_processes
from .config import Config
from .fsutil import Project
from .model import ARTIFACT, DEPS, GENERATED, PROCESS, STALE, Report

KIND_ORDER = {PROCESS: 0, DEPS: 1, ARTIFACT: 2, GENERATED: 3}


def run_scan(root: str, cfg: Config, now: Optional[float] = None) -> Report:
    now = time.time() if now is None else now
    project = Project(root, cfg.ignore_paths)
    report = Report(root=project.root)
    report.scanned = {"files": len(project.files), "file_listing": project.list_method, "config": cfg.source}
    if project.list_method != "git":
        report.notes.append("not a git work tree (or git missing): used a built-in .gitignore approximation to list files")
    if project.truncated:
        report.notes.append("file listing was capped; results may be incomplete")

    def add(res):
        report.findings.extend(res[0])
        report.ignored.extend(res[1])

    if cfg.checks.get("processes", True):
        f, ign, notes, info = check_processes(project, cfg, now)
        report.findings.extend(f)
        report.ignored.extend(ign)
        report.notes.extend(notes)
        report.scanned["processes"] = info
    if cfg.checks.get("deps", True):
        add(check_deps(project, cfg))
    if cfg.checks.get("artifacts", True):
        add(check_artifacts(project, cfg, now))
    if cfg.checks.get("generated", True):
        add(check_generated(project, cfg, now))
    report.findings.sort(key=lambda f: (f.level != STALE, KIND_ORDER.get(f.kind, 9), f.key))
    return report
