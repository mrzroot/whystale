"""Configuration: defaults plus optional ``.whystale.toml`` in the project root."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # Python 3.11+
    import tomllib as _toml  # type: ignore

    def load_toml_text(text: str) -> Dict[str, Any]:
        return _toml.loads(text)

except ImportError:  # pragma: no cover - exercised on 3.9/3.10 only
    from . import tomlmini

    def load_toml_text(text: str) -> Dict[str, Any]:
        return tomlmini.loads(text)


CONFIG_NAME = ".whystale.toml"


class ConfigError(Exception):
    pass


@dataclass
class Rule:
    """A user-defined ``sources -> outputs`` pair."""

    kind: str  # "generated" | "artifact"
    name: str
    sources: List[str]
    outputs: List[str]
    command: str = ""


@dataclass
class Config:
    grace_seconds: float = 2.0  # process start vs file mtime
    fs_grace_seconds: float = 5.0  # file vs file (builds, deps, codegen)
    ignore_paths: List[str] = field(default_factory=list)  # globs, relative to root
    ignore_processes: List[str] = field(default_factory=list)  # substrings of cmdline
    include_processes: List[str] = field(default_factory=list)  # substrings of cmdline
    checks: Dict[str, bool] = field(
        default_factory=lambda: {"processes": True, "deps": True, "artifacts": True, "generated": True}
    )
    rules: List[Rule] = field(default_factory=list)
    source: Optional[str] = None  # path of the file that was loaded


def _strlist(v: Any, where: str) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return list(v)
    raise ConfigError("%s must be a string or a list of strings" % where)


def parse_config(data: Dict[str, Any], source: Optional[str] = None) -> Config:
    cfg = Config(source=source)
    s = data.get("settings", {})
    for key in ("grace_seconds", "fs_grace_seconds"):
        if key in s:
            if not isinstance(s[key], (int, float)) or isinstance(s[key], bool) or s[key] < 0:
                raise ConfigError("settings.%s must be a non-negative number" % key)
            setattr(cfg, key, float(s[key]))
    ig = data.get("ignore", {})
    cfg.ignore_paths = _strlist(ig.get("paths"), "ignore.paths")
    cfg.ignore_processes = _strlist(ig.get("processes"), "ignore.processes")
    cfg.include_processes = _strlist(data.get("process", {}).get("include"), "process.include")
    for name, val in data.get("checks", {}).items():
        if name not in cfg.checks:
            raise ConfigError("unknown check %r (known: %s)" % (name, ", ".join(sorted(cfg.checks))))
        cfg.checks[name] = bool(val)
    for kind in ("generated", "artifact"):
        for i, item in enumerate(data.get(kind, [])):
            where = "[[%s]] #%d" % (kind, i + 1)
            if not isinstance(item, dict):
                raise ConfigError("%s must be a table" % where)
            sources = _strlist(item.get("sources"), where + ".sources")
            outputs = _strlist(item.get("outputs"), where + ".outputs")
            if not sources or not outputs:
                raise ConfigError("%s needs both `sources` and `outputs`" % where)
            cfg.rules.append(
                Rule(
                    kind=kind,
                    name=str(item.get("name") or ("custom %s %d" % (kind, i + 1))),
                    sources=sources,
                    outputs=outputs,
                    command=str(item.get("command") or ""),
                )
            )
    return cfg


def load_config(root: str, explicit: Optional[str] = None) -> Config:
    path = explicit or os.path.join(root, CONFIG_NAME)
    if not os.path.isfile(path):
        if explicit:
            raise ConfigError("config file not found: %s" % explicit)
        return Config()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = load_toml_text(fh.read())
    except Exception as exc:  # tomllib.TOMLDecodeError / TomlError / OSError
        raise ConfigError("cannot parse %s: %s" % (path, exc))
    return parse_config(data, source=path)
