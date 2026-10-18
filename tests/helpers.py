import json
import os
import time

from whystale.config import Config
from whystale.fsutil import Project
from whystale.scan import run_scan


def ago(seconds):
    return time.time() - seconds


def mk(root, rel, text="x\n", mtime=None):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def mkjson(root, rel, obj, mtime=None):
    return mk(root, rel, json.dumps(obj), mtime)


def project(root, cfg=None):
    cfg = cfg or Config()
    return Project(str(root), cfg.ignore_paths), cfg


def scan(root, cfg=None, only=None):
    cfg = cfg or Config()
    if only:
        for k in cfg.checks:
            cfg.checks[k] = k in only
    return run_scan(str(root), cfg)


def kinds(report, level=None):
    return sorted(f.kind for f in report.findings if level is None or f.level == level)
