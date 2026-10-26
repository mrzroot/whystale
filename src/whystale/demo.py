"""``whystale --demo``: an offline, deterministic scenario with real files and a real process."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Optional, Tuple

from .config import Config
from .render import render_json, render_markdown, render_text
from .scan import run_scan

SERVER_PY = '''\
import http.server, os, socketserver, sys

# Like most dev servers: read configuration once, at startup.
env = {}
for line in open(".env"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        env[k] = v

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("API_URL=%s\\n" % env.get("API_URL")).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

with socketserver.TCPServer(("127.0.0.1", 0), H) as srv:
    print("listening", srv.server_address[1], flush=True)
    srv.serve_forever()
'''

PRISMA_OLD = 'datasource db {\n  provider = "sqlite"\n  url      = "file:./dev.db"\n}\n\nmodel User {\n  id    Int    @id\n  email String\n}\n'
PRISMA_NEW = PRISMA_OLD.replace("  email String\n", "  email String\n  name  String?\n")


def _write(root: str, rel: str, text: str, age: float = 0.0) -> None:
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if age:
        t = time.time() - age
        os.utime(path, (t, t))


def build_demo_project(root: str, grace: float = 2.0) -> Tuple[subprocess.Popen, int]:
    """Create the demo project in ``root`` and start the server. Returns (process, port).

    Call :func:`edit_demo_project` afterwards to make things stale.
    """
    lock = {
        "name": "shop-web", "lockfileVersion": 3,
        "packages": {
            "": {"name": "shop-web"},
            "node_modules/express": {"version": "4.19.2"},
            "node_modules/left-pad": {"version": "1.3.0"},
        },
    }
    hidden = {
        "name": "shop-web", "lockfileVersion": 3,
        "packages": {
            "node_modules/express": {"version": "4.18.2"},
            "node_modules/left-pad": {"version": "1.3.0"},
        },
    }
    H, D, Y = 7200, 5400, 1800  # seconds: install time, last build, sources edited
    _write(root, ".gitignore", ".env\nnode_modules/\ndist/\n", H)
    _write(root, "package.json", json.dumps({"name": "shop-web", "scripts": {"dev": "node server.js", "build": "node build.js"}}, indent=2), H)
    _write(root, "package-lock.json", json.dumps(lock, indent=2), 600)
    _write(root, "node_modules/.package-lock.json", json.dumps(hidden, indent=2), H)
    _write(root, "node_modules/express/package.json", '{"name":"express","version":"4.18.2"}', H)
    _write(root, ".env", "API_URL=http://localhost:8000\n", H)
    _write(root, "src/app.js", "console.log('v1');\n", H)
    _write(root, "dist/app.js", "console.log('v1');\n", D)
    _write(root, "src/checkout.js", "console.log('new checkout');\n", Y)
    _write(root, "prisma/schema.prisma", PRISMA_NEW, 900)
    _write(root, "node_modules/.prisma/client/index.js", "// generated client\n", H)
    _write(root, "node_modules/.prisma/client/schema.prisma", PRISMA_OLD, H)
    _write(root, "server.py", SERVER_PY, H)
    proc = subprocess.Popen([sys.executable, "-u", "server.py"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    line = proc.stdout.readline().decode().strip()  # type: ignore[union-attr]
    if not line.startswith("listening"):
        proc.kill()
        raise RuntimeError("demo server failed to start")
    return proc, int(line.split()[1])


def edit_demo_project(root: str) -> None:
    """The edits that make the running server stale."""
    _write(root, ".env", "API_URL=http://localhost:9000\n")
    _write(root, "package-lock.json", open(os.path.join(root, "package-lock.json")).read())  # `npm install foo` rewrote it


def run_demo(args, st) -> int:
    quiet = args.json or args.markdown
    say = (lambda m: sys.stderr.write(m + "\n")) if quiet else (lambda m: sys.stdout.write(m + "\n"))
    tmp = tempfile.mkdtemp(prefix="whystale-demo-")
    root = os.path.join(tmp, "shop-web")
    os.makedirs(root)
    proc: Optional[subprocess.Popen] = None
    try:
        say(st.bold("whystale demo") + " - everything below is real: files in a temp dir and a spawned process.")
        say("")
        say("1. creating a tiny project in %s" % root)
        proc, port = build_demo_project(root)
        say("2. started its dev server (pid %d, port %d); it read .env once, at startup" % (proc.pid, port))
        say("   GET / -> %s" % urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5).read().decode().strip())
        cfg = Config()
        time.sleep(cfg.grace_seconds + 0.6)
        edit_demo_project(root)
        say("3. you edit .env (API_URL ...:9000) and `npm install` rewrites package-lock.json")
        say("   GET / -> %s   <- the server still serves the OLD value" % urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=5).read().decode().strip())
        say("4. whystale %s" % os.path.basename(root))
        say("")
        report = run_scan(root, cfg)
        if args.json:
            sys.stdout.write(render_json(report))
        elif args.markdown:
            sys.stdout.write(render_markdown(report))
        else:
            sys.stdout.write(render_text(report, st, verbose=args.verbose))
        sys.stdout.flush()
        expected = {"process", "deps", "artifact", "generated"}
        got = {f.kind for f in report.stale}
        if not expected <= got:
            sys.stderr.write("whystale demo: expected stale findings of kinds %s, got %s\n" % (sorted(expected), sorted(got)))
            return 1
        say("")
        say("(The demo always exits 0 when it works. Real scans exit %d when something is stale.)" % 3)
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
