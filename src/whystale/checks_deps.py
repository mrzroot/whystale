"""Stale installed dependencies: node_modules / virtualenvs older than their lockfile.

Rule used everywhere: a lockfile must be *newer* than the install marker before
anything is reported. Content comparisons can then only *clear* a finding
(the file was touched but the installed versions match) or sharpen it.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import knowledge as K
from .config import Config, load_toml_text
from .fsutil import Project, fmt_delta, fmt_time, iso, read_text
from .model import DEPS, MAYBE, STALE, Finding


def _norm_name(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def _norm_ver(v: str) -> str:
    v = v.strip().lstrip("=v").split("+", 1)[0]
    parts = v.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _cd(project: Project, d: str, cmd: str) -> str:
    return cmd if d in ("", ".") else "cd %s && %s" % (d, cmd)


def _load_json(path: str) -> Optional[Any]:
    txt = read_text(path, limit=50_000_000)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------
NODE_MARKERS = {
    "package-lock.json": ["node_modules/.package-lock.json"],
    "npm-shrinkwrap.json": ["node_modules/.package-lock.json"],
    "yarn.lock": ["node_modules/.yarn-integrity", "node_modules/.yarn-state.yml"],
    "pnpm-lock.yaml": ["node_modules/.pnpm/lock.yaml", "node_modules/.modules.yaml"],
}


def compare_npm_locks(lock: Any, hidden: Any) -> Optional[Tuple[List[Tuple[str, str, str]], List[str]]]:
    """Compare package-lock.json with node_modules/.package-lock.json.

    Returns (version_mismatches, missing_required) or None when not comparable.
    """
    if not isinstance(lock, dict) or not isinstance(hidden, dict):
        return None
    lp, hp = lock.get("packages"), hidden.get("packages")
    if not isinstance(lp, dict) or not isinstance(hp, dict):
        return None
    mism: List[Tuple[str, str, str]] = []
    missing: List[str] = []
    for key, meta in lp.items():
        if not key.startswith("node_modules/") or not isinstance(meta, dict):
            continue  # root entry and workspace members
        if meta.get("link"):
            continue
        want = meta.get("version")
        have = hp.get(key)
        if have is None:
            if meta.get("dev") or meta.get("optional") or meta.get("devOptional") or meta.get("peer") or meta.get("inBundle"):
                continue
            missing.append(key[len("node_modules/") :])
            continue
        got = have.get("version") if isinstance(have, dict) else None
        if want and got and want != got:
            mism.append((key[len("node_modules/") :], want, got))
    return mism, missing


def _norm_text(t: str) -> str:
    return " ".join(t.split())


def check_node_deps(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    ignored: List[dict] = []
    for rel in sorted(project.files):
        base = rel.rsplit("/", 1)[-1]
        if base not in NODE_MARKERS:
            continue
        d = rel.rsplit("/", 1)[0] if "/" in rel else ""
        nm = (d + "/" if d else "") + "node_modules"
        if not os.path.isdir(project.abs(nm)):
            continue
        markers = [(d + "/" if d else "") + m for m in NODE_MARKERS[base]]
        mt = [(m, project.mtime(m)) for m in markers if project.mtime(m) is not None]
        if not mt:
            continue
        marker_rel, marker_m = max(mt, key=lambda x: x[1])  # type: ignore[arg-type,return-value]
        lock_m = project.mtime(rel)
        if lock_m is None or lock_m <= marker_m + cfg.fs_grace_seconds:  # type: ignore[operator]
            continue
        pm = K.LOCKFILE_PM[base]
        subject = "%s installed state (%s) is older than %s" % (nm, marker_rel.rsplit("/", 1)[-1], rel)
        older = [{"path": rel, "what": "lockfile", "changed": iso(lock_m), "seconds_after_install": round(lock_m - marker_m, 1)}]
        fix = [_cd(project, d, K.pm_install(pm))]
        base_reason = "%s was modified %s after the last install (%s)" % (rel, fmt_delta(lock_m - marker_m), fmt_time(marker_m))
        level, evidence, notes = MAYBE, "mtime", []
        details: Dict[str, Any] = {"lockfile": rel, "install_marker": marker_rel, "package_manager": pm}
        if pm == "npm":
            cmp = compare_npm_locks(_load_json(project.abs(rel)), _load_json(project.abs(marker_rel)))
            if cmp is None:
                notes.append("could not compare package versions (no `packages` map); judged by modification time only")
            else:
                mism, missing = cmp
                if not mism and not missing:
                    ignored.append({"kind": DEPS, "subject": nm, "why": "%s is newer, but installed versions match it" % rel})
                    continue
                level, evidence = STALE, "content"
                parts = []
                if mism:
                    parts.append("%d package(s) differ, e.g. %s" % (len(mism), ", ".join("%s locked %s / installed %s" % m for m in mism[:3])))
                if missing:
                    parts.append("%d locked package(s) not installed, e.g. %s" % (len(missing), ", ".join(missing[:3])))
                base_reason += "; " + "; ".join(parts)
                details["version_mismatches"] = [{"package": a, "locked": b, "installed": c} for a, b, c in mism[:20]]
                details["missing"] = missing[:20]
        elif pm == "pnpm":
            cur = read_text(project.abs((d + "/" if d else "") + "node_modules/.pnpm/lock.yaml"))
            lock_txt = read_text(project.abs(rel))
            if cur is not None and lock_txt is not None:
                if _norm_text(cur) == _norm_text(lock_txt):
                    ignored.append({"kind": DEPS, "subject": nm, "why": "%s is newer, but identical to the installed lock copy" % rel})
                    continue
                level, evidence = STALE, "content"
                base_reason += "; it differs from the lock copy pnpm stored at install time"
            else:
                notes.append("judged by modification time only")
        else:
            notes.append("judged by modification time only (no content check for %s)" % pm)
        findings.append(
            Finding(kind=DEPS, level=level, key="deps:node:" + rel, subject=subject, reason=base_reason,
                    evidence=evidence, fix=fix, older_than=older, notes=notes, details=details)
        )
    return findings, ignored


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
def parse_requirements(text: str) -> List[Tuple[str, Optional[str], bool]]:
    """-> [(normalized name, pinned version or None, has_marker)]"""
    out: List[Tuple[str, Optional[str], bool]] = []
    text = text.replace("\\\n", " ")
    for raw in text.splitlines():
        line = re.split(r"\s+#", raw.strip(), maxsplit=1)[0].strip()
        if not line or line.startswith(("#", "-", ".", "/")) or "://" in line:
            continue
        marker = ";" in line
        line = line.split(";", 1)[0]
        line = " ".join(t for t in line.split() if not t.startswith("--"))
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest.startswith("@"):
            continue
        pin = re.match(r"^===?\s*([A-Za-z0-9._+!-]+)$", rest)
        ver = pin.group(1) if pin and not rest.endswith(".*") else None
        out.append((_norm_name(m.group(1)), ver, marker))
    return out


def parse_lock_packages(path: str, base: str, own_name: Optional[str]) -> Optional[List[Tuple[str, Optional[str], bool]]]:
    txt = read_text(path)
    if txt is None:
        return None
    try:
        if base == "Pipfile.lock":
            data = json.loads(txt)
            res = []
            for sec in ("default", "develop"):
                for name, meta in (data.get(sec) or {}).items():
                    v = meta.get("version") if isinstance(meta, dict) else None
                    res.append((_norm_name(name), v.lstrip("=") if v else None, sec == "develop"))
            return res
        data = load_toml_text(txt)
    except Exception:
        return None
    res = []
    for pkg in data.get("package", []):
        if not isinstance(pkg, dict) or "name" not in pkg:
            continue
        name = _norm_name(str(pkg["name"]))
        if own_name and name == own_name:
            continue
        src = pkg.get("source")
        if isinstance(src, dict) and any(k in src for k in ("editable", "virtual", "directory", "path")):
            continue
        if isinstance(src, dict) and src.get("type") in ("directory", "file", "git") and base == "poetry.lock":
            continue
        res.append((name, str(pkg["version"]) if pkg.get("version") else None, False))
    return res


def find_site_packages(venv: str) -> List[str]:
    cands = glob.glob(os.path.join(venv, "lib", "python*", "site-packages")) + [os.path.join(venv, "Lib", "site-packages")]
    return [c for c in cands if os.path.isdir(c)]


def installed_packages(site_dirs: List[str]) -> Tuple[Dict[str, str], float]:
    pkgs: Dict[str, str] = {}
    newest = 0.0
    for sp in site_dirs:
        try:
            entries = os.scandir(sp)
        except OSError:
            continue
        for e in entries:
            if not e.name.endswith(".dist-info"):
                continue
            stem = e.name[: -len(".dist-info")]
            name, sep, ver = stem.rpartition("-")
            if not sep:
                continue
            pkgs[_norm_name(name)] = ver
            try:
                newest = max(newest, e.stat().st_mtime)
            except OSError:
                pass
    return pkgs, newest


PY_SPECS = ("poetry.lock", "uv.lock", "Pipfile.lock")


def _project_name(project: Project, d: str) -> Optional[str]:
    txt = read_text(project.abs((d + "/" if d else "") + "pyproject.toml"))
    if not txt:
        return None
    try:
        data = load_toml_text(txt)
    except Exception:
        return None
    name = (data.get("project") or {}).get("name") or ((data.get("tool") or {}).get("poetry") or {}).get("name")
    return _norm_name(str(name)) if name else None


def check_python_deps(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    findings: List[Finding] = []
    ignored: List[dict] = []
    by_dir: Dict[str, List[str]] = {}
    for rel in project.files:
        base = rel.rsplit("/", 1)[-1]
        if base in PY_SPECS or re.match(r"^requirements[^/]*\.txt$", base):
            by_dir.setdefault(rel.rsplit("/", 1)[0] if "/" in rel else "", []).append(rel)
    for d, specs in sorted(by_dir.items()):
        prefix = d + "/" if d else ""
        venv_rel = None
        for cand in (".venv", "venv", "env", ".env"):
            if os.path.isfile(project.abs(prefix + cand + "/pyvenv.cfg")):
                venv_rel = prefix + cand
                break
        if venv_rel is None:
            ve = os.environ.get("VIRTUAL_ENV")
            if ve and not d and os.path.realpath(ve).startswith(os.path.realpath(project.root) + os.sep):
                venv_rel = project.rel(ve)
        if venv_rel is None:
            continue
        site = find_site_packages(project.abs(venv_rel))
        installed, newest = installed_packages(site)
        if not installed:
            continue
        own = _project_name(project, d)
        for rel in sorted(specs):
            base = rel.rsplit("/", 1)[-1]
            spec_m = project.mtime(rel)
            if spec_m is None or spec_m <= newest + cfg.fs_grace_seconds:
                continue
            if base in PY_SPECS:
                wanted = parse_lock_packages(project.abs(rel), base, own)
            else:
                txt = read_text(project.abs(rel))
                wanted = parse_requirements(txt) if txt is not None else None
            fix_cmd = {
                "poetry.lock": "poetry install", "uv.lock": "uv sync", "Pipfile.lock": "pipenv sync",
            }.get(base, "%s/bin/python -m pip install -r %s" % (venv_rel, rel.rsplit("/", 1)[-1]))
            fix = [_cd(project, d, fix_cmd)]
            older = [{"path": rel, "what": "dependency spec", "changed": iso(spec_m),
                      "seconds_after_install": round(spec_m - newest, 1)}]
            subject = "%s packages are older than %s" % (venv_rel, rel)
            base_reason = "%s was modified %s after the newest package was installed (%s)" % (rel, fmt_delta(spec_m - newest), fmt_time(newest))
            details: Dict[str, Any] = {"spec": rel, "venv": venv_rel}
            if not wanted:
                findings.append(Finding(kind=DEPS, level=MAYBE, key="deps:py:" + rel, subject=subject, reason=base_reason,
                                        evidence="mtime", fix=fix, older_than=older,
                                        notes=["could not read package versions from the file; judged by modification time only"],
                                        details=details))
                continue
            mism, missing = [], []
            for name, ver, flag in wanted:
                have = installed.get(name)
                if have is None:
                    if not flag:
                        missing.append(name)
                    continue
                if ver and _norm_ver(ver) != _norm_ver(have):
                    mism.append((name, ver, have))
            if not mism and not missing:
                ignored.append({"kind": DEPS, "subject": venv_rel, "why": "%s is newer, but installed versions satisfy it" % rel})
                continue
            parts = []
            if mism:
                parts.append("%d package(s) differ, e.g. %s" % (len(mism), ", ".join("%s wants %s / installed %s" % m for m in mism[:3])))
            if missing:
                parts.append("%d package(s) not installed, e.g. %s" % (len(missing), ", ".join(missing[:3])))
            details["version_mismatches"] = [{"package": a, "wanted": b, "installed": c} for a, b, c in mism[:20]]
            details["missing"] = missing[:20]
            notes = []
            level = STALE if mism else MAYBE
            if not mism:
                notes.append("only missing packages found; they may belong to an optional group or extra you chose not to install")
            findings.append(Finding(kind=DEPS, level=level, key="deps:py:" + rel, subject=subject,
                                    reason=base_reason + "; " + "; ".join(parts), evidence="content", fix=fix,
                                    older_than=older, notes=notes, details=details))
    return findings, ignored


def check_deps(project: Project, cfg: Config) -> Tuple[List[Finding], List[dict]]:
    f1, i1 = check_node_deps(project, cfg)
    f2, i2 = check_python_deps(project, cfg)
    return f1 + f2, i1 + i2
