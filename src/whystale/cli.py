"""Command line interface."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional

from . import __version__
from .config import ConfigError, load_config
from .render import (EXIT_STALE, exit_code, make_style, render_json, render_markdown, render_text)
from .scan import run_scan

EPILOG = """\
exit codes: 0 nothing stale | 3 stale things found | 2 usage/config error
  (findings marked "maybe" only count with --strict; --no-fail always exits 0)

examples:
  whystale                      scan the current directory
  whystale ~/code/shop --json   machine-readable output
  whystale --demo               offline demo in a temp dir with a real process
  whystale || echo "restart/rebuild needed"     as an agent or CI hook
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whystale",
        description="Find what is older than what it was built from: dev servers started before .env/lockfile/config "
                    "changed, build output older than sources, installed deps older than the lockfile, generated code "
                    "older than its schema. Read-only; prints the exact command to refresh each item.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("project_dir", nargs="?", default=".", help="project directory to scan (default: .)")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="print JSON")
    fmt.add_argument("--markdown", action="store_true", help="print Markdown (paste into an agent prompt)")
    p.add_argument("--demo", action="store_true", help="build a throwaway project with a real process and scan it (offline)")
    p.add_argument("--watch", nargs="?", const=2.0, type=float, metavar="SECONDS",
                   help="re-scan every SECONDS (default 2) and print what changes")
    p.add_argument("--strict", action="store_true", help="count 'maybe' findings in the exit code too")
    p.add_argument("--no-fail", action="store_true", help="always exit 0 (just report)")
    p.add_argument("--only", metavar="CHECKS", help="comma list of: processes,deps,artifacts,generated")
    p.add_argument("--config", metavar="FILE", help="path to a .whystale.toml (default: PROJECT_DIR/.whystale.toml)")
    p.add_argument("-v", "--verbose", action="store_true", help="also list items cleared by a content check")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument("--version", action="version", version="whystale " + __version__)
    p.add_argument("--iterations", type=int, default=0, help=argparse.SUPPRESS)  # bounded --watch, for tests
    return p


def _emit(report, args, st) -> None:
    if args.json:
        sys.stdout.write(render_json(report))
    elif args.markdown:
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(render_text(report, st, verbose=args.verbose))
    sys.stdout.flush()


def _apply_only(cfg, only: Optional[str]) -> None:
    if not only:
        return
    wanted = {x.strip() for x in only.split(",") if x.strip()}
    unknown = wanted - set(cfg.checks)
    if unknown:
        raise ConfigError("unknown check(s): %s (known: %s)" % (", ".join(sorted(unknown)), ", ".join(sorted(cfg.checks))))
    for k in cfg.checks:
        cfg.checks[k] = k in wanted


def _watch(root, cfg, args, st) -> int:
    interval = max(0.2, args.watch)
    report = run_scan(root, cfg)
    _emit(report, args, st)
    prev = {f.key: f for f in report.findings}
    n = 0
    try:
        while True:
            if args.iterations and n >= args.iterations:
                break
            time.sleep(interval)
            n += 1
            report = run_scan(root, cfg)
            cur = {f.key: f for f in report.findings}
            stamp = time.strftime("%H:%M:%S")
            for k, f in cur.items():
                if k not in prev:
                    print("[%s] %s now %s: %s" % (stamp, f.kind, f.level, f.subject))
                    print("          why: " + f.reason)
                    for c in f.fix:
                        print("          fix: " + c)
            for k, f in prev.items():
                if k not in cur:
                    print("[%s] %s resolved: %s" % (stamp, f.kind, f.subject))
            sys.stdout.flush()
            prev = cur
    except KeyboardInterrupt:
        pass
    return 0 if args.no_fail else exit_code(report, args.strict)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    st = make_style(color=False if (args.no_color or args.json or args.markdown) else None)
    try:
        if args.demo:
            from .demo import run_demo
            return run_demo(args, st)
        root = os.path.abspath(args.project_dir)
        if not os.path.isdir(root):
            sys.stderr.write("whystale: not a directory: %s\n" % args.project_dir)
            return 2
        cfg = load_config(root, args.config)
        _apply_only(cfg, args.only)
        if args.watch is not None:
            return _watch(root, cfg, args, st)
        report = run_scan(root, cfg)
    except ConfigError as exc:
        sys.stderr.write("whystale: %s\n" % exc)
        return 2
    _emit(report, args, st)
    return 0 if args.no_fail else exit_code(report, args.strict)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
