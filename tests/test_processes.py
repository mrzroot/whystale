import os
import shutil
import subprocess
import sys
import time

import pytest

from whystale import procs
from whystale.checks_process import (env_already_applied, evaluate_processes, parse_dotenv)
from whystale.config import Config
from whystale.fsutil import Project
from whystale.procs import Proc
from helpers import ago, mk, scan

linux_only = pytest.mark.skipif(not procs.have_proc(), reason="needs /proc")


def run(tmp_path, plist, cfg=None, env_reader=lambda pid: None):
    cfg = cfg or Config()
    proj = Project(str(tmp_path))
    return evaluate_processes(proj, cfg, plist, set(), env_reader)


def P(pid, start, argv, cwd, ppid=1):
    return Proc(pid=pid, ppid=ppid, start=start, argv=argv, cwd=str(cwd))


def test_env_changed_after_start_is_stale(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(10))
    f, _ = run(tmp_path, [P(100, ago(60), ["node", "server.js"], tmp_path)])
    assert len(f) == 1 and f[0].level == "stale" and f[0].evidence == "process-start"
    assert f[0].fix[0] == "kill 100" and f[0].fix[1].endswith("node server.js")
    assert f[0].older_than[0]["path"] == ".env"


def test_env_older_than_start_is_fine(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(600))
    assert run(tmp_path, [P(100, ago(60), ["node", "server.js"], tmp_path)])[0] == []


def test_grace_edge_for_processes(tmp_path):
    start = ago(100)
    mk(tmp_path, ".env", "A=1\n", start + 1.5)  # within 2 s grace
    pr = [P(100, start, ["node", "s.js"], tmp_path)]
    assert run(tmp_path, pr)[0] == []
    os.utime(tmp_path / ".env", (start + 2.5, start + 2.5))
    assert len(run(tmp_path, pr)[0]) == 1
    assert run(tmp_path, pr, Config(grace_seconds=5))[0] == []


def test_templates_and_unrelated_files_are_ignored(tmp_path):
    for n in (".env.example", ".env.sample", ".env.local.template", "README.md", "src.js"):
        mk(tmp_path, n, "x", ago(1))
    assert run(tmp_path, [P(100, ago(60), ["node", "s.js"], tmp_path)])[0] == []


def test_process_outside_project_or_shell_or_unknown_is_skipped(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    mk(tmp_path, "proj/.env", "A=1\n", ago(1))
    proj = tmp_path / "proj"
    plist = [
        P(1, ago(60), ["node", "s.js"], other),         # cwd outside the project
        P(2, ago(60), ["bash"], proj),                   # interactive shell
        P(3, ago(60), ["vim", ".env"], proj),            # editor
        P(4, ago(60), ["/usr/bin/sleep", "100"], proj),  # not a runtime
        P(5, ago(60), ["node", "s.js"], proj),
    ]
    f, _ = run(proj, plist)
    assert [x.details["pid"] for x in f] == [5]


def test_non_runtime_listening_on_a_port_counts_as_a_server(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(1))
    quiet = P(1, ago(60), ["./mybinary"], tmp_path)
    server = Proc(2, 1, ago(60), ["./myserver"], str(tmp_path), ports=[8080])
    f, _ = run(tmp_path, [quiet, server])
    assert [x.details["pid"] for x in f] == [2] and f[0].details["ports"] == [8080]


def test_config_include_and_ignore_processes(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(1))
    plist = [P(1, ago(60), ["/opt/bin/mydaemon", "--x"], tmp_path), P(2, ago(60), ["node", "tailscaled-ui.js"], tmp_path)]
    f, _ = run(tmp_path, plist, Config(include_processes=["mydaemon"], ignore_processes=["tailscaled"]))
    assert [x.details["pid"] for x in f] == [1]


def test_vite_is_maybe_because_it_restarts_itself(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(1))
    mk(tmp_path, "vite.config.ts", "x", ago(1))
    f, _ = run(tmp_path, [P(7, ago(60), ["node", str(tmp_path) + "/node_modules/vite/bin/vite.js", "--port", "5173"], tmp_path)])
    assert len(f) == 1 and f[0].level == "maybe" and f[0].details["runner"] == "Vite dev server"
    assert any("restarts" in n for n in f[0].notes)


def test_django_runserver_reloads_settings_but_not_env(tmp_path):
    mk(tmp_path, "settings.py", "x", ago(1))
    cmd = [sys.executable, "manage.py", "runserver"]
    f, _ = run(tmp_path, [P(7, ago(60), cmd, tmp_path)])
    assert f[0].level == "maybe"
    mk(tmp_path, ".env", "A=1\n", ago(1))
    f, _ = run(tmp_path, [P(7, ago(60), cmd, tmp_path)])
    assert f[0].level == "stale"  # .env is not reloaded by runserver


def test_manifest_change_is_only_maybe(tmp_path):
    mk(tmp_path, "package.json", "{}", ago(1))
    f, _ = run(tmp_path, [P(7, ago(60), ["node", "s.js"], tmp_path)])
    assert f[0].level == "maybe"


def test_docker_files_only_matter_for_compose(tmp_path):
    mk(tmp_path, "docker-compose.yml", "x", ago(1))
    assert run(tmp_path, [P(7, ago(60), ["node", "s.js"], tmp_path)])[0] == []
    f, _ = run(tmp_path, [P(8, ago(60), ["docker", "compose", "up"], tmp_path)])
    assert len(f) == 1 and f[0].details["runner"] == "docker compose"


def test_wrapper_chain_is_one_finding_led_by_the_top_process(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(1))
    plist = [
        Proc(10, 1, ago(300), ["bash"], str(tmp_path)),
        Proc(11, 10, ago(200), ["npm", "run", "dev"], str(tmp_path)),
        Proc(12, 11, ago(199), ["sh", "-c", "node server.js"], str(tmp_path)),
        Proc(13, 12, ago(198), ["node", "server.js"], str(tmp_path), ports=[3000]),
    ]
    f, _ = run(tmp_path, plist)
    assert len(f) == 1
    assert f[0].details["pid"] == 11 and f[0].fix[0] == "kill 11" and f[0].fix[1].endswith("npm run dev")
    assert 13 in f[0].details["members"]


def test_restarted_child_is_judged_by_its_own_start(tmp_path):
    # nodemon-style: wrapper old, child restarted after .env changed -> not stale
    mk(tmp_path, ".env", "A=1\n", ago(100))
    plist = [Proc(20, 1, ago(500), ["node", "nodemon"], str(tmp_path)),
             Proc(21, 20, ago(50), ["node", "app.js"], str(tmp_path))]
    assert run(tmp_path, plist)[0] == []


def test_pid_reuse_changes_identity(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(30))
    old = P(100, ago(60), ["node", "s.js"], tmp_path)
    reused = P(100, ago(5), ["node", "other.js"], tmp_path)  # same pid, new process started after the edit
    f_old, _ = run(tmp_path, [old])
    f_new, _ = run(tmp_path, [reused])
    assert len(f_old) == 1 and f_new == []


def test_subdirectory_process_reads_root_env_too(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(1))
    (tmp_path / "apps" / "web").mkdir(parents=True)
    f, _ = run(tmp_path, [P(7, ago(60), ["node", "s.js"], tmp_path / "apps" / "web")])
    assert len(f) == 1


def test_parse_dotenv_and_content_check(tmp_path):
    assert parse_dotenv("A=1\nexport B='two words'\n# c\nC=\"x\"\nD=3 # trailing\n") == {"A": "1", "B": "two words", "C": "x", "D": "3"}
    assert parse_dotenv("A=$B\n") is None
    assert parse_dotenv("A=\"multi\n") is None
    mk(tmp_path, ".env", "A=1\nB=two\n", ago(1))
    f = str(tmp_path / ".env")
    assert env_already_applied(f, {"A": "1", "B": "two", "PATH": "/x"})
    assert not env_already_applied(f, {"A": "1"})          # key absent: cannot prove anything
    assert not env_already_applied(f, {"A": "1", "B": "old"})
    assert not env_already_applied(f, None)


def test_env_values_already_in_environment_clears_finding(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(1))
    pr = [P(7, ago(60), ["node", "s.js"], tmp_path)]
    f, ignored = run(tmp_path, pr, env_reader=lambda pid: {"A": "1"})
    assert f == [] and "already in its environment" in ignored[0]["why"]


# -- parsers (recorded macOS-style output; real macOS is not available in CI here) --------
PS_OUT = """  501     1 Sat Oct 17 09:01:02 2026 /usr/sbin/cfprefsd agent
12345   501 Sun Oct  4 11:22:33 2026 node /Users/me/shop web/node_modules/.bin/vite --port 5173
 777   501 Sun Oct 18 08:00:01 2026 python3 -m http.server 8000
garbage line
"""
LSOF_CWD = "p12345\nn/Users/me/shop web\np777\nn/Users/me/api\n"
LSOF_LISTEN = "p12345\nn*:5173\nn[::1]:5173\np777\nn127.0.0.1:8000\n"


def test_parse_ps_fixture():
    ps = procs.parse_ps(PS_OUT)
    assert [p.pid for p in ps] == [501, 12345, 777]
    p = ps[1]
    assert p.ppid == 501 and p.comm == "node" and "vite" in p.cmdline
    t = time.localtime(p.start)
    assert (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec) == (2026, 10, 4, 11, 22, 33)


def test_parse_lsof_fixtures():
    assert procs.parse_lsof_cwd(LSOF_CWD) == {12345: "/Users/me/shop web", 777: "/Users/me/api"}
    assert procs.parse_lsof_listen(LSOF_LISTEN) == {12345: [5173], 777: [8000]}


def test_parse_proc_stat_with_awkward_comm():
    line = "4242 (my (weird) app) S 17 4242 17 0 -1 4194560 100 0 0 0 1 2 0 0 20 0 3 0 987654 1 2 3\n"
    assert procs.parse_proc_stat(line) == (17, 987654)
    assert procs.parse_proc_stat("garbage") is None


def test_macos_style_pipeline_with_fixtures(tmp_path):
    ps = procs.parse_ps(PS_OUT)
    cwd = procs.parse_lsof_cwd(LSOF_CWD)
    root = tmp_path / "shop web"
    root.mkdir()
    mk(root, ".env", "A=1\n", ago(1))
    for p in ps:
        p.cwd = str(root) if p.pid == 12345 else cwd.get(p.pid)
        p.start = ago(120) if p.pid == 12345 else p.start
    f, _ = evaluate_processes(Project(str(root)), Config(), ps, set(), lambda pid: None)
    assert len(f) == 1 and f[0].details["pid"] == 12345
    assert f[0].details["runner"] == "Vite dev server" and f[0].level == "maybe"


# -- real processes --------------------------------------------------------------------
@pytest.fixture
def sleeper(tmp_path):
    procs_started = []

    def start(cwd, extra=()):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", *extra], cwd=str(cwd),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs_started.append(p)
        time.sleep(0.2)
        return p

    yield start
    for p in procs_started:
        p.kill()
        p.wait()


@linux_only
def test_linux_start_time_is_accurate(tmp_path, sleeper):
    before = time.time()
    p = sleeper(tmp_path)
    table = {x.pid: x for x in procs.list_processes_linux()}
    assert abs(table[p.pid].start - before) < 2.0
    assert table[p.pid].cwd == str(tmp_path.resolve()) or table[p.pid].cwd == str(tmp_path)


@linux_only
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_process_title_rewrite_is_split_into_words(tmp_path):
    # node's process.title overwrites the whole command line with one string (what `npm exec vite` does)
    p = subprocess.Popen(["node", "-e", "process.title='npm exec vite --port 5199'; setTimeout(()=>{},60000)"], cwd=str(tmp_path))
    try:
        time.sleep(0.6)
        table = {x.pid: x for x in procs.list_processes_linux()}
        assert table[p.pid].argv[:3] == ["npm", "exec", "vite"] and table[p.pid].argv[-1] == "5199"
    finally:
        p.kill()
        p.wait()


@linux_only
def test_real_process_goes_stale_when_env_is_touched(tmp_path, sleeper):
    mk(tmp_path, ".env", "A=1\n", ago(3600))
    p = sleeper(tmp_path)
    assert scan(tmp_path, only={"processes"}).findings == []
    time.sleep(2.3)
    mk(tmp_path, ".env", "A=2\n")
    r = scan(tmp_path, only={"processes"})
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.level == "stale" and f.details["pid"] == p.pid
    assert f.fix[0] == "kill %d" % p.pid
    # the python process is cleared once it is restarted after the change
    p.kill()
    p.wait()
    sleeper(tmp_path)
    assert scan(tmp_path, only={"processes"}).findings == []


@linux_only
def test_real_process_values_in_environment_clear_the_finding(tmp_path):
    mk(tmp_path, ".env", "WHYSTALE_TEST_VAR=hello\n", ago(3600))
    env = dict(os.environ, WHYSTALE_TEST_VAR="hello")
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(tmp_path), env=env)
    try:
        time.sleep(2.5)
        mk(tmp_path, ".env", "WHYSTALE_TEST_VAR=hello\n")
        r = scan(tmp_path, only={"processes"})
        assert r.findings == [] and r.ignored
    finally:
        p.kill()
        p.wait()


@linux_only
def test_real_listening_port_is_reported(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(3600))
    code = ("import socket,time;s=socket.socket();s.bind(('127.0.0.1',0));s.listen();"
            "print(s.getsockname()[1],flush=True);time.sleep(120)")
    p = subprocess.Popen([sys.executable, "-c", code], cwd=str(tmp_path), stdout=subprocess.PIPE)
    try:
        port = int(p.stdout.readline())
        time.sleep(2.5)
        mk(tmp_path, ".env", "A=2\n")
        f = scan(tmp_path, only={"processes"}).findings[0]
        assert f.details["ports"] == [port] and (":%d" % port) in f.subject
    finally:
        p.kill()
        p.wait()


@pytest.mark.skipif(shutil.which("ps") is None, reason="ps not installed")
def test_ps_backend_end_to_end(tmp_path, sleeper, monkeypatch):
    """The macOS code path (ps + lsof, /proc readlink when lsof is absent), exercised on Linux."""
    mk(tmp_path, ".env", "A=1\n", ago(3600))
    p = sleeper(tmp_path)
    time.sleep(2.3)
    mk(tmp_path, ".env", "A=2\n")
    monkeypatch.setenv("WHYSTALE_BACKEND", "ps")
    if shutil.which("lsof") is None and not procs.have_proc():
        pytest.skip("neither lsof nor /proc available for cwd lookup")
    r = scan(tmp_path, only={"processes"})
    assert r.scanned["processes"]["backend"] == "ps"
    assert [f.details["pid"] for f in r.findings] == [p.pid]


@linux_only
def test_real_non_runtime_listener_is_found_via_port(tmp_path):
    import stat
    mk(tmp_path, ".env", "A=1\n", ago(3600))
    # a copy of the interpreter under a name that is not a known runtime
    exe = tmp_path / "mysrv"
    shutil.copy(getattr(sys, "_base_executable", sys.executable), exe)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    code = ("import socket,time;s=socket.socket();s.bind(('127.0.0.1',0));s.listen();print(s.getsockname()[1],flush=True);time.sleep(60)")
    try:
        p = subprocess.Popen([str(exe), "-c", code], cwd=str(tmp_path), stdout=subprocess.PIPE)
    except OSError:
        pytest.skip("cannot run a copied interpreter here")
    try:
        line = p.stdout.readline()
        if not line:
            pytest.skip("copied interpreter does not start (venv layout)")
        time.sleep(2.5)
        mk(tmp_path, ".env", "A=2\n")
        r = scan(tmp_path, only={"processes"})
        assert [f.details["pid"] for f in r.findings] == [p.pid]
    finally:
        p.kill()
        p.wait()
