"""Small helpers around package.json / Makefile used to suggest exact commands."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from . import knowledge as K
from .fsutil import Project, read_text


def load_package_json(project: Project, d: str) -> Dict[str, object]:
    txt = read_text(project.abs((d + "/" if d else "") + "package.json"))
    if not txt:
        return {}
    try:
        data = json.loads(txt)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def scripts_of(project: Project, d: str) -> Dict[str, str]:
    s = load_package_json(project, d).get("scripts")
    return {k: v for k, v in s.items() if isinstance(v, str)} if isinstance(s, dict) else {}


def detect_pm(project: Project, d: str) -> str:
    """Package manager from the nearest lockfile at or above ``d``."""
    cur = d
    while True:
        for name, pm in K.LOCKFILE_PM.items():
            if project.mtime((cur + "/" if cur else "") + name) is not None:
                return pm
        if not cur:
            return "npm"
        cur = cur.rsplit("/", 1)[0] if "/" in cur else ""


def infer_script(project: Project, d: str, needles: List[str]) -> Optional[str]:
    """Name of a package.json script whose command contains one of ``needles``."""
    for name, cmd in scripts_of(project, d).items():
        if any(n in cmd or n in name for n in needles):
            return name
    return None


def infer_make_target(project: Project, d: str, needles: List[str]) -> Optional[str]:
    txt = read_text(project.abs((d + "/" if d else "") + "Makefile"))
    if not txt:
        return None
    for m in re.finditer(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", txt, re.M):
        if any(n in m.group(1) for n in needles):
            return m.group(1)
    return None
