"""False-positive guards: a project whose artifacts are all fresher than their inputs is clean."""

import os
import random
import time

import pytest

from whystale.config import Config
from helpers import mk, mkjson, scan

NOW = time.time()


def fresh_project(tmp_path, rnd):
    """Every output gets an mtime later than every one of its inputs (by > the grace period)."""
    base = NOW - 10 * 86400
    inputs = lambda: base + rnd.uniform(0, 86400)           # noqa: E731
    middle = lambda: base + 86400 * 1.2 + rnd.uniform(0, 86400 * 0.6)  # noqa: E731  (codegen output)
    outputs = lambda: base + 2 * 86400 + rnd.uniform(0, 86400)  # noqa: E731
    lock = {"packages": {"node_modules/a": {"version": "1"}, "node_modules/b": {"version": "2"}}}
    mkjson(tmp_path, "package.json", {"scripts": {"build": "x"}}, inputs())
    mkjson(tmp_path, "package-lock.json", lock, inputs())
    mkjson(tmp_path, "node_modules/.package-lock.json", lock, outputs())
    for i in range(rnd.randint(1, 8)):
        mk(tmp_path, "src/f%d.ts" % i, "x", inputs())
    mk(tmp_path, "public/logo.svg", "x", inputs())
    mk(tmp_path, "dist/a.js", "x", outputs())
    mk(tmp_path, "dist/b.js", "x", outputs())
    mk(tmp_path, "prisma/schema.prisma", "model A { id Int }", inputs())
    mk(tmp_path, "node_modules/.prisma/client/index.js", "x", outputs())
    mk(tmp_path, "a.proto", "x", inputs())
    mk(tmp_path, "gen/a_pb2.py", "x", outputs())
    mk(tmp_path, "openapi.json", "{}", inputs())
    mk(tmp_path, "src/generated/api.ts", "openapi", middle())  # it is also a build input
    mk(tmp_path, "requirements.txt", "requests==2\n", inputs())
    mk(tmp_path, ".venv/pyvenv.cfg", "x", outputs())
    d = tmp_path / ".venv/lib/python3.12/site-packages/requests-2.dist-info"
    d.mkdir(parents=True)
    t = outputs()
    os.utime(d, (t, t))


@pytest.mark.parametrize("seed", range(25))
def test_fresh_project_has_zero_findings(tmp_path, seed):
    fresh_project(tmp_path, random.Random(seed))
    r = scan(tmp_path)
    assert r.findings == [], [f.subject for f in r.findings]


def test_the_same_project_goes_stale_when_one_input_is_touched(tmp_path):
    fresh_project(tmp_path, random.Random(1))
    assert scan(tmp_path).findings == []
    for rel in ("src/f0.ts", "package-lock.json", "prisma/schema.prisma", "a.proto", "openapi.json", "requirements.txt"):
        p = tmp_path / rel
        os.utime(p, (NOW, NOW))
    kinds = {f.kind for f in scan(tmp_path).findings}
    # (nothing runs here, so no process finding; the touched lockfile/requirements are content-identical
    # to what is installed, so the deps check correctly stays quiet)
    assert kinds == {"artifact", "generated"}
    mkjson(tmp_path, "node_modules/.package-lock.json", {"packages": {"node_modules/a": {"version": "0.0.1"}}}, NOW - 5 * 86400)
    mk(tmp_path, "requirements.txt", "requests==3\n", NOW)
    r = scan(tmp_path)
    assert {f.kind for f in r.findings} == {"artifact", "generated", "deps"}
    assert len([f for f in r.findings if f.kind == "deps"]) == 2


def test_config_can_disable_checks(tmp_path):
    fresh_project(tmp_path, random.Random(2))
    os.utime(tmp_path / "src" / "f0.ts", (NOW, NOW))
    cfg = Config()
    cfg.checks["artifacts"] = False
    assert scan(tmp_path, cfg).findings == []
