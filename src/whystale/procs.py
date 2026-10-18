"""Process discovery: /proc on Linux, ``ps`` + ``lsof`` elsewhere (macOS, BSD)."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Proc:
    pid: int
    ppid: int
    start: float  # epoch seconds
    argv: List[str]
    cwd: Optional[str] = None
    ports: List[int] = field(default_factory=list)

    @property
    def comm(self) -> str:
        base = os.path.basename(self.argv[0]) if self.argv else ""
        # process titles such as "next-server (v14.2.3)" carry spaces
        return base.split()[0] if base.split() else ""

    @property
    def cmdline(self) -> str:
        return " ".join(self.argv)


# -- Linux ---------------------------------------------------------------------
def _clk_tck() -> int:
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError, AttributeError):
        return 100


def _boot_time() -> Optional[float]:
    try:
        with open("/proc/stat", "r") as fh:
            for line in fh:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def parse_proc_stat(text: str) -> Optional[Tuple[int, int]]:
    """Return (ppid, starttime_ticks) from the contents of /proc/PID/stat."""
    rp = text.rfind(")")
    if rp == -1:
        return None
    fields = text[rp + 2 :].split()
    try:
        return int(fields[1]), int(fields[19])
    except (IndexError, ValueError):
        return None


def have_proc() -> bool:
    return os.path.exists("/proc/self/stat") and os.path.exists("/proc/stat")


def list_processes_linux() -> List[Proc]:
    boot = _boot_time()
    if boot is None:
        raise OSError("cannot read boot time from /proc/stat")
    tck = _clk_tck()
    procs: List[Proc] = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        base = "/proc/" + name
        try:
            with open(base + "/stat", "r") as fh:
                parsed = parse_proc_stat(fh.read())
            if parsed is None:
                continue
            with open(base + "/cmdline", "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if not raw:  # kernel thread or zombie
            continue
        argv = [a.decode("utf-8", "replace") for a in raw.rstrip(b"\0").split(b"\0")]
        if len(argv) == 1 and " " in argv[0]:
            # the process rewrote its title ("npm exec vite --port 5199"): recover the words
            try:
                argv = shlex.split(argv[0])
            except ValueError:
                argv = argv[0].split()
        try:
            cwd: Optional[str] = os.readlink(base + "/cwd")
        except OSError:
            cwd = None
        procs.append(Proc(pid=int(name), ppid=parsed[0], start=boot + parsed[1] / float(tck), argv=argv, cwd=cwd))
    return procs


def _linux_listen_inodes() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fn, "r") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) > 9 and parts[3] == "0A":  # LISTEN
                        out[parts[9]] = int(parts[1].rsplit(":", 1)[1], 16)
        except (OSError, ValueError):
            continue
    return out


def linux_ports(pids: List[int]) -> Dict[int, List[int]]:
    inodes = _linux_listen_inodes()
    res: Dict[int, List[int]] = {}
    if not inodes:
        return res
    for pid in pids:
        fd_dir = "/proc/%d/fd" % pid
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        ports = set()
        for fd in fds:
            try:
                link = os.readlink(fd_dir + "/" + fd)
            except OSError:
                continue
            if link.startswith("socket:["):
                ino = link[8:-1]
                if ino in inodes:
                    ports.add(inodes[ino])
        if ports:
            res[pid] = sorted(ports)
    return res


def read_environ(pid: int) -> Optional[Dict[str, str]]:
    """Environment the process was started with (Linux only; None if unreadable)."""
    try:
        with open("/proc/%d/environ" % pid, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    env: Dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, _, v = item.partition(b"=")
            env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
    return env


# -- ps / lsof (macOS and fallback) ------------------------------------------------
_PS_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\w{3}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s+(.*)$")


def parse_ps(text: str) -> List[Proc]:
    """Parse ``ps -axo pid=,ppid=,lstart=,command=`` (C locale)."""
    procs: List[Proc] = []
    for line in text.splitlines():
        m = _PS_RE.match(line)
        if not m:
            continue
        try:
            start = time.mktime(time.strptime(" ".join(m.group(3).split()), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            continue
        cmd = m.group(4).strip()
        if not cmd:
            continue
        try:
            argv = shlex.split(cmd)
        except ValueError:
            argv = cmd.split()
        procs.append(Proc(pid=int(m.group(1)), ppid=int(m.group(2)), start=start, argv=argv))
    return procs


def parse_lsof_cwd(text: str) -> Dict[int, str]:
    """Parse ``lsof -a -d cwd -F pn`` output into {pid: cwd}."""
    res: Dict[int, str] = {}
    pid: Optional[int] = None
    for line in text.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = None
        elif line.startswith("n") and pid is not None:
            res[pid] = line[1:]
    return res


def parse_lsof_listen(text: str) -> Dict[int, List[int]]:
    """Parse ``lsof -nP -iTCP -sTCP:LISTEN -F pn`` output into {pid: [ports]}."""
    res: Dict[int, List[int]] = {}
    pid: Optional[int] = None
    for line in text.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = None
        elif line.startswith("n") and pid is not None:
            m = re.search(r":(\d+)$", line)
            if m:
                lst = res.setdefault(pid, [])
                if int(m.group(1)) not in lst:
                    lst.append(int(m.group(1)))
    return {k: sorted(v) for k, v in res.items()}


def _run(cmd: List[str], timeout: int = 20) -> Optional[str]:
    env = dict(os.environ, LC_ALL="C", LANG="C")
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode not in (0, 1):  # lsof exits 1 when it found nothing for some filters
        return None
    return p.stdout.decode("utf-8", "replace")


def list_processes_ps() -> Tuple[List[Proc], List[str]]:
    notes: List[str] = []
    out = _run(["ps", "-axo", "pid=,ppid=,lstart=,command="])
    if out is None:
        raise OSError("`ps` failed")
    procs = parse_ps(out)
    cwds = _run(["lsof", "-a", "-d", "cwd", "-F", "pn"])
    if cwds is not None:
        m = parse_lsof_cwd(cwds)
        for p in procs:
            p.cwd = m.get(p.pid)
    elif have_proc():
        for p in procs:
            try:
                p.cwd = os.readlink("/proc/%d/cwd" % p.pid)
            except OSError:
                pass
    else:
        notes.append("`lsof` not found: cannot tell which processes run inside the project")
    return procs, notes


def list_processes(backend: Optional[str] = None) -> Tuple[List[Proc], List[str], str]:
    """Return (processes, notes, backend_name). ``backend``: 'proc' | 'ps' | None=auto."""
    backend = backend or os.environ.get("WHYSTALE_BACKEND") or ("proc" if have_proc() else "ps")
    if backend == "proc":
        return list_processes_linux(), [], "proc"
    procs, notes = list_processes_ps()
    return procs, notes, "ps"


def attach_ports(procs: List[Proc], backend: str) -> None:
    if not procs:
        return
    if backend == "proc":
        m = linux_ports([p.pid for p in procs])
    else:
        out = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pn"])
        m = parse_lsof_listen(out) if out else {}
    for p in procs:
        p.ports = m.get(p.pid, [])


def ancestors(pid: int, table: Dict[int, Proc]) -> List[int]:
    chain: List[int] = []
    seen = set()
    cur = table.get(pid)
    while cur is not None and cur.ppid not in seen and cur.ppid > 0:
        seen.add(cur.ppid)
        chain.append(cur.ppid)
        cur = table.get(cur.ppid)
    return chain
