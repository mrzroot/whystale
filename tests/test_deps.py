import os

from whystale.config import Config
from helpers import ago, kinds, mk, mkjson, scan

LOCK = {"lockfileVersion": 3, "packages": {
    "": {"name": "app"},
    "node_modules/a": {"version": "1.0.0"},
    "node_modules/b": {"version": "2.0.0"},
    "node_modules/devonly": {"version": "3.0.0", "dev": True},
    "node_modules/opt": {"version": "1.0.0", "optional": True},
}}


def hidden(**overrides):
    pk = {"node_modules/a": {"version": "1.0.0"}, "node_modules/b": {"version": "2.0.0"}}
    pk.update(overrides)
    return {"lockfileVersion": 3, "packages": {k: v for k, v in pk.items() if v is not None}}


def npm_project(tmp_path, lock, hid, lock_age=100, install_age=1000):
    mkjson(tmp_path, "package-lock.json", lock, ago(lock_age))
    mkjson(tmp_path, "node_modules/.package-lock.json", hid, ago(install_age))
    mk(tmp_path, "package.json", "{}", ago(5000))


def test_npm_version_mismatch_is_stale_with_content_proof(tmp_path):
    npm_project(tmp_path, LOCK, hidden(**{"node_modules/b": {"version": "1.9.0"}}))
    r = scan(tmp_path, only={"deps"})
    f = r.findings[0]
    assert (f.kind, f.level, f.evidence) == ("deps", "stale", "content")
    assert "b locked 2.0.0 / installed 1.9.0" in f.reason
    assert f.fix == ["npm ci"]


def test_npm_lock_touched_but_versions_equal_is_cleared(tmp_path):
    npm_project(tmp_path, LOCK, hidden())
    r = scan(tmp_path, only={"deps"})
    assert r.findings == []
    assert r.ignored and "installed versions match" in r.ignored[0]["why"]


def test_npm_missing_required_package_is_stale_but_dev_and_optional_are_not(tmp_path):
    npm_project(tmp_path, LOCK, hidden(**{"node_modules/b": None}))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.level == "stale" and "not installed, e.g. b" in f.reason
    assert "devonly" not in f.reason and "opt" not in f.reason


def test_npm_omit_dev_install_is_fresh(tmp_path):
    # lock newer than marker, but only dev/optional packages are absent
    npm_project(tmp_path, LOCK, hidden())
    assert scan(tmp_path, only={"deps"}).findings == []


def test_npm_install_newer_than_lock_is_fresh(tmp_path):
    npm_project(tmp_path, LOCK, hidden(**{"node_modules/b": {"version": "0.1"}}), lock_age=1000, install_age=100)
    assert scan(tmp_path, only={"deps"}).findings == []


def test_equal_timestamp_and_grace_edge(tmp_path):
    t = ago(500)
    mkjson(tmp_path, "package-lock.json", LOCK, t)
    mkjson(tmp_path, "node_modules/.package-lock.json", hidden(**{"node_modules/b": {"version": "0"}}), t)
    assert scan(tmp_path, only={"deps"}).findings == []  # identical mtimes
    os.utime(tmp_path / "package-lock.json", (t + 4, t + 4))  # inside the 5 s grace
    assert scan(tmp_path, only={"deps"}).findings == []
    os.utime(tmp_path / "package-lock.json", (t + 6, t + 6))  # just outside
    assert kinds(scan(tmp_path, only={"deps"})) == ["deps"]
    cfg = Config(fs_grace_seconds=10)
    assert scan(tmp_path, cfg, only={"deps"}).findings == []


def test_yarn_is_mtime_only_and_maybe(tmp_path):
    mk(tmp_path, "yarn.lock", "# lock\n", ago(100))
    mk(tmp_path, "node_modules/.yarn-integrity", "{}", ago(1000))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert (f.level, f.evidence) == ("maybe", "mtime")
    assert f.fix == ["yarn install --frozen-lockfile"]
    assert any("modification time only" in n for n in f.notes)


def test_pnpm_identical_copy_cleared_and_differing_copy_stale(tmp_path):
    mk(tmp_path, "pnpm-lock.yaml", "lockfileVersion: 9\nfoo: 1\n", ago(100))
    mk(tmp_path, "node_modules/.pnpm/lock.yaml", "lockfileVersion: 9\nfoo: 1\n", ago(1000))
    assert scan(tmp_path, only={"deps"}).findings == []
    mk(tmp_path, "node_modules/.pnpm/lock.yaml", "lockfileVersion: 9\nfoo: 0\n", ago(1000))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.level == "stale" and f.fix == ["pnpm install --frozen-lockfile"]


def test_workspace_subdir_fix_command_has_cd(tmp_path):
    mkjson(tmp_path, "web/package-lock.json", LOCK, ago(100))
    mkjson(tmp_path, "web/node_modules/.package-lock.json", hidden(**{"node_modules/a": {"version": "0.1"}}), ago(1000))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.fix == ["cd web && npm ci"]


def make_venv(tmp_path, pkgs, age=1000, name=".venv"):
    mk(tmp_path, name + "/pyvenv.cfg", "home = /usr/bin\n", ago(age))
    sp = "%s/lib/python3.12/site-packages" % name
    for pkg, ver in pkgs.items():
        mk(tmp_path, "%s/%s-%s.dist-info/METADATA" % (sp, pkg.replace("-", "_"), ver), "Name: %s\n" % pkg, ago(age))
        os.utime(tmp_path / sp / ("%s-%s.dist-info" % (pkg.replace("-", "_"), ver)), (ago(age), ago(age)))


def test_requirements_pin_mismatch_is_stale(tmp_path):
    make_venv(tmp_path, {"requests": "2.30.0", "flask": "3.0.0"})
    mk(tmp_path, "requirements.txt", "requests==2.31.0\nFlask>=3\n# c\n-e .\n", ago(100))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.level == "stale" and "requests wants 2.31.0 / installed 2.30.0" in f.reason
    assert f.fix[0].endswith("-m pip install -r requirements.txt")


def test_requirements_touched_but_satisfied_is_cleared(tmp_path):
    make_venv(tmp_path, {"requests": "2.31.0", "typing-extensions": "4.9.0"})
    mk(tmp_path, "requirements.txt", "requests==2.31.0\ntyping_extensions>=4\n", ago(100))
    r = scan(tmp_path, only={"deps"})
    assert r.findings == [] and r.ignored


def test_requirements_missing_only_is_maybe(tmp_path):
    make_venv(tmp_path, {"requests": "2.31.0"})
    mk(tmp_path, "requirements.txt", "requests==2.31.0\nrich\nwin-only; sys_platform=='win32'\n", ago(100))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.level == "maybe" and "rich" in f.reason and "win-only" not in f.reason


def test_uv_lock_mismatch_skips_editable_project(tmp_path):
    make_venv(tmp_path, {"requests": "2.30.0"})
    mk(tmp_path, "pyproject.toml", '[project]\nname = "myproj"\nversion = "0.1.0"\n', ago(5000))
    mk(tmp_path, "uv.lock", 'version = 1\n[[package]]\nname = "requests"\nversion = "2.31.0"\n'
       '[[package]]\nname = "myproj"\nversion = "0.1.0"\nsource = { editable = "." }\n', ago(100))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.level == "stale" and f.fix == ["uv sync"] and "myproj" not in f.reason


def test_pipfile_lock(tmp_path):
    make_venv(tmp_path, {"django": "4.2.0"})
    mkjson(tmp_path, "Pipfile.lock", {"default": {"django": {"version": "==5.0.0"}}, "develop": {}}, ago(100))
    f = scan(tmp_path, only={"deps"}).findings[0]
    assert f.level == "stale" and f.fix == ["pipenv sync"]


def test_no_venv_or_node_modules_means_nothing_to_judge(tmp_path):
    mk(tmp_path, "requirements.txt", "requests==9\n", ago(100))
    mkjson(tmp_path, "package-lock.json", LOCK, ago(100))
    assert scan(tmp_path, only={"deps"}).findings == []


def test_dot_env_file_is_not_mistaken_for_venv(tmp_path):
    mk(tmp_path, ".env", "A=1\n", ago(100))
    mk(tmp_path, "requirements.txt", "requests==9\n", ago(100))
    assert scan(tmp_path, only={"deps"}).findings == []
