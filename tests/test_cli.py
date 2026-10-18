import json
import os
import subprocess
import sys
import threading
import time

import pytest

from whystale import __version__
from whystale.cli import main
from helpers import ago, mk, mkjson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def stale_project(tmp_path):
    mkjson(tmp_path, "package.json", {"scripts": {"build": "x"}}, ago(9000))
    mk(tmp_path, "src/a.ts", "1", ago(100))
    mk(tmp_path, "dist/a.js", "1", ago(1000))
    return tmp_path


def clean_project(tmp_path):
    mkjson(tmp_path, "package.json", {"scripts": {"build": "x"}}, ago(9000))
    mk(tmp_path, "src/a.ts", "1", ago(1000))
    mk(tmp_path, "dist/a.js", "1", ago(100))
    return tmp_path


def test_clean_exits_zero(tmp_path, capsys):
    assert main([str(clean_project(tmp_path)), "--no-color"]) == 0
    assert "nothing stale" in capsys.readouterr().out


def test_stale_exits_three_and_prints_fix(tmp_path, capsys):
    assert main([str(stale_project(tmp_path)), "--no-color"]) == 3
    out = capsys.readouterr().out
    assert "STALE (1)" in out and "dist is older than its sources" in out and "fix:    npm run build" in out
    assert "src/a.ts" in out and "Exit code 3" in out


def test_no_fail_and_only(tmp_path, capsys):
    d = str(stale_project(tmp_path))
    assert main([d, "--no-fail"]) == 0
    assert main([d, "--only", "deps,processes"]) == 0
    assert main([d, "--only", "artifacts"]) == 3
    capsys.readouterr()
    assert main([d, "--only", "bogus"]) == 2


def test_strict_counts_maybe(tmp_path):
    mk(tmp_path, "yarn.lock", "x", ago(100))
    mk(tmp_path, "node_modules/.yarn-integrity", "{}", ago(1000))
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--strict"]) == 3


def test_json_output_schema(tmp_path, capsys):
    assert main([str(stale_project(tmp_path)), "--json"]) == 3
    data = json.loads(capsys.readouterr().out)
    assert data["tool"] == "whystale" and data["version"] == __version__
    assert data["stale"] is True and data["summary"] == {"stale": 1, "maybe": 0, "ignored": 0}
    f = data["findings"][0]
    assert set(f) == {"kind", "level", "key", "subject", "reason", "evidence", "fix", "older_than", "notes", "details"}
    assert f["kind"] == "artifact" and f["fix"] == ["npm run build"]


def test_json_clean(tmp_path, capsys):
    assert main([str(clean_project(tmp_path)), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["stale"] is False and data["findings"] == []


def test_markdown_output(tmp_path, capsys):
    main([str(stale_project(tmp_path)), "--markdown"])
    out = capsys.readouterr().out
    assert out.startswith("# whystale report") and "```sh" in out and "npm run build" in out


def test_errors(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2
    mk(tmp_path, ".whystale.toml", "[checks]\nbogus = true\n")
    assert main([str(tmp_path)]) == 2
    assert "unknown check" in capsys.readouterr().err


def test_config_file_changes_behaviour(tmp_path):
    d = stale_project(tmp_path)
    mk(d, ".whystale.toml", '[ignore]\npaths = ["src/**"]\n')
    assert main([str(d)]) == 0


def test_verbose_lists_cleared_items(tmp_path, capsys):
    mkjson(tmp_path, "package-lock.json", {"packages": {"node_modules/a": {"version": "1"}}}, ago(100))
    mkjson(tmp_path, "node_modules/.package-lock.json", {"packages": {"node_modules/a": {"version": "1"}}}, ago(1000))
    assert main([str(tmp_path), "-v", "--no-color"]) == 0
    assert "Ignored" in capsys.readouterr().out


def test_watch_prints_transitions(tmp_path, capsys):
    d = clean_project(tmp_path)
    os.utime(d / "dist" / "a.js", (ago(1000), ago(1000)))
    os.utime(d / "src" / "a.ts", (ago(2000), ago(2000)))

    def edit():
        time.sleep(0.5)
        os.utime(d / "src" / "a.ts", (time.time(), time.time()))
        time.sleep(0.8)
        os.utime(d / "dist" / "a.js", (time.time() + 20, time.time() + 20))

    t = threading.Thread(target=edit)
    t.start()
    code = main([str(d), "--watch", "0.3", "--iterations", "7", "--no-color"])
    t.join()
    out = capsys.readouterr().out
    assert "artifact now stale: dist is older than its sources" in out
    assert "artifact resolved" in out
    assert code == 0  # resolved at the end


def run_module(*args):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    return subprocess.run([sys.executable, "-m", "whystale", *args], capture_output=True, text=True, env=env, timeout=60)


def test_module_entry_and_version():
    r = run_module("--version")
    assert r.returncode == 0 and __version__ in r.stdout


def test_demo_text():
    r = run_module("--demo", "--no-color")
    assert r.returncode == 0, r.stderr
    for needle in ("STALE (4)", "process", "deps", "build", "generated", "kill ", "npm ci", "npm run build", "npx prisma generate",
                   "the server still serves the OLD value"):
        assert needle in r.stdout


def test_demo_json_is_valid_and_complete():
    r = run_module("--demo", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert {f["kind"] for f in data["findings"] if f["level"] == "stale"} == {"process", "deps", "artifact", "generated"}
