import os
import subprocess
import shutil

import pytest

from whystale.config import Config
from helpers import ago, kinds, mk, mkjson, scan


def node_build(tmp_path, build_age=1000, src_age=100, scripts=None):
    mkjson(tmp_path, "package.json", {"name": "x", "scripts": scripts if scripts is not None else {"build": "vite build"}}, ago(9000))
    mk(tmp_path, "src/main.ts", "1", ago(src_age))
    mk(tmp_path, "dist/assets/index.js", "1", ago(build_age))


def test_dist_older_than_sources_is_stale(tmp_path):
    node_build(tmp_path)
    r = scan(tmp_path, only={"artifacts"})
    f = r.findings[0]
    assert (f.kind, f.level, f.evidence) == ("artifact", "stale", "mtime")
    assert f.fix == ["npm run build"] and f.older_than[0]["path"] == "src/main.ts"


def test_fresh_build_is_clean(tmp_path):
    node_build(tmp_path, build_age=100, src_age=1000)
    assert scan(tmp_path, only={"artifacts"}).findings == []


def test_grace_edge(tmp_path):
    node_build(tmp_path, build_age=500, src_age=500)
    assert scan(tmp_path, only={"artifacts"}).findings == []
    os.utime(tmp_path / "src" / "main.ts", (ago(496), ago(496)))  # 4 s newer: within grace
    assert scan(tmp_path, only={"artifacts"}).findings == []
    os.utime(tmp_path / "src" / "main.ts", (ago(494), ago(494)))  # 6 s newer
    assert kinds(scan(tmp_path, only={"artifacts"})) == ["artifact"]


def test_package_manager_comes_from_lockfile(tmp_path):
    node_build(tmp_path)
    mk(tmp_path, "pnpm-lock.yaml", "x", ago(9000))
    assert scan(tmp_path, only={"artifacts"}).findings[0].fix == ["pnpm run build"]


def test_missing_build_script_is_honest(tmp_path):
    node_build(tmp_path, scripts={})
    f = scan(tmp_path, only={"artifacts"}).findings[0]
    assert f.fix[0].startswith("#") and f.notes


def test_gitignored_and_test_files_do_not_count(tmp_path):
    node_build(tmp_path, build_age=1000, src_age=2000)
    mk(tmp_path, ".gitignore", "generated.ts\n", ago(9000))
    mk(tmp_path, "generated.ts", "x", ago(10))
    mk(tmp_path, "src/main.test.ts", "x", ago(10))
    mk(tmp_path, "tests/unit.ts", "x", ago(10))
    mk(tmp_path, "README.md", "x", ago(10))
    mk(tmp_path, "eslint.config.js", "x", ago(10))
    mk(tmp_path, "src/types.d.ts", "x", ago(10))
    assert scan(tmp_path, only={"artifacts"}).findings == []


def test_user_ignore_path(tmp_path):
    node_build(tmp_path)
    cfg = Config(ignore_paths=["src/**"])
    assert scan(tmp_path, cfg, only={"artifacts"}).findings == []


def test_non_js_build_dir_is_skipped(tmp_path):
    mkjson(tmp_path, "package.json", {"scripts": {"build": "x"}}, ago(9000))
    mk(tmp_path, "src/a.ts", "1", ago(10))
    mk(tmp_path, "build/output.bin", "1", ago(1000))
    assert scan(tmp_path, only={"artifacts"}).findings == []


def test_next_dir_and_nested_packages(tmp_path):
    mkjson(tmp_path, "apps/web/package.json", {"scripts": {"build": "next build"}}, ago(9000))
    mk(tmp_path, "apps/web/app/page.tsx", "1", ago(100))
    mk(tmp_path, "apps/web/.next/BUILD_ID", "1", ago(1000))
    mkjson(tmp_path, "apps/api/package.json", {"scripts": {"build": "tsc"}}, ago(9000))
    mk(tmp_path, "apps/api/src/index.ts", "1", ago(1000))
    mk(tmp_path, "apps/api/dist/index.js", "1", ago(100))
    r = scan(tmp_path, only={"artifacts"})
    assert [f.key for f in r.findings] == ["artifact:apps/web/.next"]
    assert r.findings[0].fix == ["cd apps/web && npm run build"]


def test_public_assets_count_as_sources(tmp_path):
    node_build(tmp_path, build_age=1000, src_age=2000)
    mk(tmp_path, "public/logo.svg", "<svg/>", ago(10))
    assert kinds(scan(tmp_path, only={"artifacts"})) == ["artifact"]


def test_rust_target_uses_newest_profile(tmp_path):
    mk(tmp_path, "Cargo.toml", "[package]\n", ago(9000))
    mk(tmp_path, "src/main.rs", "fn main(){}", ago(100))
    mk(tmp_path, "target/debug/app", "bin", ago(1000))
    mk(tmp_path, "target/debug/app.d", "d", ago(10))  # dep-info files do not count
    mk(tmp_path, "target/release/app", "bin", ago(50000))  # older profile is ignored
    r = scan(tmp_path, only={"artifacts"})
    assert [f.fix for f in r.findings] == [["cargo build"]]
    mk(tmp_path, "target/release/app", "bin", ago(900))
    os.utime(tmp_path / "target" / "debug" / "app", (ago(2000), ago(2000)))
    assert scan(tmp_path, only={"artifacts"}).findings[0].fix == ["cargo build --release"]


def test_custom_artifact_rule(tmp_path):
    mk(tmp_path, ".whystale.toml", '[[artifact]]\nname = "docs"\nsources = ["docs/**/*.md", "mkdocs.yml"]\n'
       'outputs = ["site/**"]\ncommand = "mkdocs build"\n', ago(9000))
    mk(tmp_path, "mkdocs.yml", "x", ago(9000))
    mk(tmp_path, "docs/a.md", "x", ago(100))
    mk(tmp_path, "site/index.html", "x", ago(1000))
    from whystale.config import load_config
    cfg = load_config(str(tmp_path))
    f = scan(tmp_path, cfg, only={"generated"}).findings[0]
    assert (f.kind, f.fix) == ("artifact", ["mkdocs build"]) and f.older_than[0]["path"] == "docs/a.md"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_ignored_source_is_skipped_with_git_listing(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    node_build(tmp_path, build_age=1000, src_age=2000)
    mk(tmp_path, ".gitignore", "dist/\nsrc/gen.ts\n", ago(9000))
    mk(tmp_path, "src/gen.ts", "x", ago(10))
    r = scan(tmp_path, only={"artifacts"})
    assert r.scanned["file_listing"] == "git" and r.findings == []
