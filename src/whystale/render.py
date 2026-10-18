"""Renderers: text, markdown, JSON."""

from __future__ import annotations

import json
import sys
import time
from typing import List, Optional

from . import __version__
from .fsutil import fmt_delta, fmt_time
from .model import KIND_LABEL, MAYBE, STALE, Finding, Report

EXIT_STALE = 3


class Style:
    def __init__(self, color: bool, unicode_ok: bool):
        self.color = color
        self.u = unicode_ok

    def c(self, code: str, s: str) -> str:
        return "\033[%sm%s\033[0m" % (code, s) if self.color else s

    def red(self, s): return self.c("31;1", s)
    def yellow(self, s): return self.c("33;1", s)
    def green(self, s): return self.c("32;1", s)
    def dim(self, s): return self.c("2", s)
    def bold(self, s): return self.c("1", s)

    @property
    def x(self): return "✗" if self.u else "x"
    @property
    def q(self): return "?" 
    @property
    def ok(self): return "✓" if self.u else "OK"
    @property
    def dot(self): return "·" if self.u else "-"


def make_style(stream=None, color: Optional[bool] = None) -> Style:
    import os
    stream = stream or sys.stdout
    if color is None:
        color = bool(getattr(stream, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    enc = (getattr(stream, "encoding", None) or "ascii").lower()
    return Style(color, "utf" in enc)


def exit_code(report: Report, strict: bool = False) -> int:
    if report.stale or (strict and report.maybe):
        return EXIT_STALE
    return 0


def _fmt_older(o: dict) -> str:
    if "seconds_after_start" in o:
        return "%s (%s) changed %s after start" % (o["path"], o.get("what", ""), fmt_delta(o["seconds_after_start"]))
    for k in ("seconds_after_install", "seconds_after_build", "seconds_after_generation"):
        if k in o:
            word = {"seconds_after_install": "install", "seconds_after_build": "build", "seconds_after_generation": "generation"}[k]
            return "%s (%s) changed %s after %s" % (o["path"], o.get("what", ""), fmt_delta(o[k]), word)
    return o["path"]


def render_text(report: Report, st: Style, verbose: bool = False, now: Optional[float] = None) -> str:
    out: List[str] = []
    out.append(st.bold("whystale %s" % __version__) + " " + st.dim("%s %s" % (st.dot, report.root)))
    sc = report.scanned
    bits = ["%d files (%s)" % (sc.get("files", 0), sc.get("file_listing", "?"))]
    if "processes" in sc and sc["processes"].get("backend"):
        bits.append("%d process(es) in project (%s)" % (sc["processes"].get("processes_in_project", 0), sc["processes"]["backend"]))
    out.append(st.dim("checked " + (" %s " % st.dot).join(bits)))
    out.append("")
    stale, maybe = report.stale, report.maybe
    if not report.findings:
        out.append(st.green("%s nothing stale" % st.ok) + " - no process, install, build or generated file is older than what it came from.")
    for title, items, paint, sym in (
        ("STALE", stale, st.red, st.x),
        ("MAYBE", maybe, st.yellow, st.q),
    ):
        if not items:
            continue
        if title == "STALE":
            out.append(paint("STALE (%d)" % len(items)))
        else:
            out.append(paint("MAYBE (%d)" % len(items)) + st.dim("  heuristic: does not fail the exit code unless --strict"))
        out.append("")
        for f in items:
            out.append("%s %s %s %s" % (paint(sym), st.bold(KIND_LABEL[f.kind]), st.dot, f.subject))
            out.append("    why:    " + f.reason)
            for o in f.older_than[:4]:
                out.append("    newer:  " + _fmt_older(o))
            if len(f.older_than) > 4:
                out.append("            ... and %d more" % (len(f.older_than) - 4))
            out.append("    proof:  " + {"mtime": "modification times", "content": "file contents + modification times", "process-start": "process start time vs file modification times"}.get(f.evidence, f.evidence))
            for n in f.notes:
                out.append("    note:   " + n)
            for i, cmd in enumerate(f.fix):
                lead = "    fix:    " if i == 0 else "            "
                out.append(lead + (st.dim(cmd) if cmd.startswith("#") else st.green(cmd)))
            out.append("")
    if verbose and report.ignored:
        out.append(st.dim("Ignored (looked stale by time, cleared by content):"))
        for i in report.ignored:
            out.append(st.dim("  - %s: %s" % (i.get("subject"), i.get("why"))))
        out.append("")
    if report.notes:
        for n in report.notes:
            out.append(st.dim("note: " + n))
        out.append("")
    if report.findings:
        out.append("%d stale, %d maybe." % (len(stale), len(maybe)) + (" Exit code %d." % EXIT_STALE if stale else ""))
    return "\n".join(out).rstrip() + "\n"


def render_markdown(report: Report) -> str:
    out = ["# whystale report", "", "Project: `%s`" % report.root, ""]
    if not report.findings:
        out.append("Nothing stale.")
    for label, items in (("Stale", report.stale), ("Maybe stale (heuristic)", report.maybe)):
        if not items:
            continue
        out += ["## %s (%d)" % (label, len(items)), ""]
        for f in items:
            out.append("### %s: %s" % (KIND_LABEL[f.kind], f.subject))
            out.append("- **Why:** " + f.reason)
            for o in f.older_than[:4]:
                out.append("- **Newer input:** " + _fmt_older(o))
            for n in f.notes:
                out.append("- **Note:** " + n)
            out.append("- **Fix:**")
            out.append("  ```sh")
            out += ["  " + c for c in f.fix]
            out.append("  ```")
            out.append("")
    for n in report.notes:
        out.append("> note: " + n)
    return "\n".join(out).rstrip() + "\n"


def report_dict(report: Report, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    return {
        "tool": "whystale",
        "version": __version__,
        "project": report.root,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
        "stale": bool(report.stale),
        "summary": {"stale": len(report.stale), "maybe": len(report.maybe), "ignored": len(report.ignored)},
        "exit_code_if_stale": EXIT_STALE,
        "findings": [f.to_dict() for f in report.findings],
        "ignored": report.ignored,
        "notes": report.notes,
        "scanned": report.scanned,
    }


def render_json(report: Report, now: Optional[float] = None) -> str:
    return json.dumps(report_dict(report, now), indent=2, ensure_ascii=False) + "\n"
