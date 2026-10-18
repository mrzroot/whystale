"""Stale processes: started before a file they read at startup was changed."""

from __future__ import annotations

import os
import re
import shlex
from typing import Callable, Dict, List, Optional, Tuple

from . import knowledge as K
from .config import Config
from .fsutil import Project, fmt_delta, fmt_time, iso
from .model import MAYBE, PROCESS, STALE, Finding
from .procs import Proc, ancestors, attach_ports, list_processes, read_environ

EnvReader = Callable[[int], Optional[Dict[str, str]]]


def parse_dotenv(text: str) -> Optional[Dict[str, str]]:
    """Parse simple dotenv text. Returns None if anything is too exotic to judge."""
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*)$", line)
        if not m:
            return None
        key, val = m.group(1), m.group(2)
        if val[:1] in ("'", '"'):
            q = val[0]
            end = val.find(q, 1)
            if end == -1:
                return None  # multi-line value
            val = val[1:end]
            if q == '"' and "\\" in val:
                return None
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        if "$" in val or "`" in val:
            return None  # interpolation: cannot judge
        out[key] = val
    return out


def env_already_applied(env_file: str, environ: Optional[Dict[str, str]]) -> bool:
    """True when every assignment in the file is already in the process environment.

    Only a *positive* proof is used: frameworks that load .env in-process leave the
    keys absent from the startup environment, and then we cannot tell (returns False).
    """
    if environ is None:
        return False
    try:
        with open(env_file, "r", encoding="utf-8", errors="replace") as fh:
            parsed = parse_dotenv(fh.read())
    except OSError:
        return False
    if parsed is None or not parsed:
        return False
    return all(environ.get(k) == v for k, v in parsed.items())


def _in_project(cwd: Optional[str], root_real: str) -> bool:
    if not cwd:
        return False
    try:
        cwd_real = os.path.realpath(cwd)
    except OSError:
        return False
    return cwd_real == root_real or cwd_real.startswith(root_real + os.sep)


def _dirs_up(cwd_real: str, root_real: str) -> List[str]:
    dirs = []
    cur = cwd_real
    while True:
        dirs.append(cur)
        if cur == root_real or len(cur) <= len(root_real):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return dirs


def select_candidates(project: Project, cfg: Config, procs: List[Proc], self_pids: set) -> Dict[int, Proc]:
    root_real = os.path.realpath(project.root)
    cands: Dict[int, Proc] = {}
    for p in procs:
        if p.pid in self_pids or not _in_project(p.cwd, root_real):
            continue
        cmd = p.cmdline
        if any(s in cmd for s in cfg.ignore_processes):
            continue
        forced = any(s in cmd for s in cfg.include_processes)
        if not forced and p.comm.lower() in K.IGNORED_COMMS:
            continue
        if forced or K.is_runtime(p.comm) or p.ports:  # anything listening on a TCP port is a server
            cands[p.pid] = p
    return cands


def group_wrappers(cands: Dict[int, Proc], table: Dict[int, Proc]) -> Dict[int, List[Proc]]:
    """Group `npm run dev` -> sh -> node vite chains under their top-most candidate."""
    groups: Dict[int, List[Proc]] = {}
    for pid, p in cands.items():
        top = pid
        for a in ancestors(pid, table):
            if a in cands:
                top = a
            elif a in table and table[a].comm.lower() in K.SHELL_COMMS:
                continue
            else:
                break
        groups.setdefault(top, []).append(p)
    return groups


def _short(cmd: str, n: int = 70) -> str:
    return cmd if len(cmd) <= n else cmd[: n - 1] + "…"


def evaluate_processes(
    project: Project,
    cfg: Config,
    procs: List[Proc],
    self_pids: Optional[set] = None,
    env_reader: EnvReader = read_environ,
    ports_backend: Optional[str] = None,
) -> Tuple[List[Finding], List[dict]]:
    """Pure-ish core: decide staleness for already-listed processes."""
    root_real = os.path.realpath(project.root)
    table = {p.pid: p for p in procs}
    if ports_backend:
        attach_ports([p for p in procs if _in_project(p.cwd, root_real)], ports_backend)
    cands = select_candidates(project, cfg, procs, self_pids or set())
    groups = group_wrappers(cands, table)
    findings: List[Finding] = []
    ignored: List[dict] = []
    for top_pid, members in sorted(groups.items()):
        members.sort(key=lambda m: m.pid)
        leader = table[top_pid] if top_pid in table else members[0]
        eff_start = max(m.start for m in members)
        runner = None
        for m in [leader] + members:
            runner = K.match_runner(m.cmdline)
            if runner:
                break
        runner_name = str(runner["name"]) if runner else None
        auto = set(runner["auto"]) if runner else set()  # type: ignore[arg-type]

        # directories the group's processes could read config from: cwd .. project root
        dirs: List[str] = []
        for m in members:
            if m.cwd and _in_project(m.cwd, root_real):
                for d in _dirs_up(os.path.realpath(m.cwd), root_real):
                    if d not in dirs:
                        dirs.append(d)
        changed: List[dict] = []
        for d in dirs:
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                try:
                    if not e.is_file():
                        continue
                    cls = K.classify_file(e.name, runner_name)
                    if cls is None:
                        continue
                    mt = e.stat().st_mtime
                except OSError:
                    continue
                rel = project.rel(e.path)
                if project.is_ignored(rel):
                    continue
                if mt <= eff_start + cfg.grace_seconds:
                    continue
                if cls == "env":
                    applied = any(env_already_applied(e.path, env_reader(m.pid)) for m in members)
                    if applied:
                        ignored.append(
                            {"kind": PROCESS, "subject": rel, "why": "changed after pid %d started, but every value is already in its environment" % leader.pid}
                        )
                        continue
                level = K.FILE_CLASSES[cls]["level"]
                note = ""
                if cls in auto:
                    level = MAYBE
                    note = str(runner["why"])  # type: ignore[index]
                changed.append(
                    {"path": rel, "class": cls, "label": K.FILE_CLASSES[cls]["label"], "mtime": mt,
                     "level": level, "note": note}
                )
        if not changed:
            continue
        changed.sort(key=lambda c: (c["level"] != STALE, -c["mtime"]))
        level = STALE if any(c["level"] == STALE for c in changed) else MAYBE
        ports = sorted({p for m in members for p in m.ports})
        title = runner_name or leader.comm
        port_txt = " :" + ",".join(str(p) for p in ports) if ports else ""
        subject = "%s — `%s` (pid %d%s)" % (title, _short(leader.cmdline), leader.pid, port_txt)
        newest = max(c["mtime"] for c in changed)
        if level == STALE:
            reason = (
                "started %s, but %d file(s) it reads at startup changed afterwards "
                "(latest %s later)" % (fmt_time(eff_start), len(changed), fmt_delta(newest - eff_start))
            )
        else:
            reason = (
                "started %s; files changed afterwards, but %s probably handles them without a restart"
                % (fmt_time(eff_start), runner_name)
            )
        notes: List[str] = []
        for c in changed:
            if c["note"] and c["note"] not in notes:
                notes.append(c["note"])
        if level == STALE and not runner:
            notes.append("no reload behaviour is known for this process, so it most likely read the file(s) once at startup")
        if len(members) > 1:
            notes.append("includes child/wrapper processes: " + ", ".join("%d %s" % (m.pid, m.comm) for m in members if m.pid != leader.pid))
        cwd = leader.cwd or project.root
        fix = ["kill %d" % leader.pid, "cd %s && %s" % (shlex.quote(cwd), " ".join(shlex.quote(a) for a in leader.argv))]
        findings.append(
            Finding(
                kind=PROCESS, level=level, key="process:%d:%d" % (leader.pid, int(leader.start)),
                subject=subject, reason=reason, evidence="process-start", fix=fix,
                older_than=[
                    {"path": c["path"], "what": c["label"], "changed": iso(c["mtime"]),
                     "seconds_after_start": round(c["mtime"] - eff_start, 1), "level": c["level"]}
                    for c in changed
                ],
                notes=notes,
                details={"pid": leader.pid, "started": iso(eff_start), "cwd": cwd, "ports": ports,
                         "runner": runner_name, "members": [m.pid for m in members]},
            )
        )
    return findings, ignored


def check_processes(project: Project, cfg: Config, now: float) -> Tuple[List[Finding], List[dict], List[str], dict]:
    notes: List[str] = []
    try:
        procs, pnotes, backend = list_processes()
    except OSError as exc:
        return [], [], ["process check skipped: %s" % exc], {"backend": None, "processes": 0}
    notes.extend(pnotes)
    table = {p.pid: p for p in procs}
    me = os.getpid()
    self_pids = {me, *ancestors(me, table)}
    findings, ignored = evaluate_processes(project, cfg, procs, self_pids, ports_backend=backend,
                                           env_reader=read_environ if backend == "proc" else (lambda pid: None))
    root_real = os.path.realpath(project.root)
    in_proj = sum(1 for p in procs if _in_project(p.cwd, root_real) and p.pid not in self_pids)
    return findings, ignored, notes, {"backend": backend, "processes_in_project": in_proj}
