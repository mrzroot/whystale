import pytest

from whystale import tomlmini
from whystale.config import Config, ConfigError, load_config, parse_config, load_toml_text
from helpers import mk

SAMPLE = '''
# comment
[settings]
grace_seconds = 3
fs_grace_seconds = 7.5

[ignore]
paths = ["dist/legacy/**", 'vendor/**']
processes = [
  "tailscaled",   # trailing comment
  "ollama",
]

[process]
include = ["my-daemon"]

[checks]
deps = false

[[generated]]
name = "api client"
sources = ["api/spec.yaml"]
outputs = ["src/client/**"]
command = "make client"

[[artifact]]
name = "docs"
sources = ["docs/**/*.md", "mkdocs.yml"]
outputs = ["site/**"]
command = "mkdocs build"
'''

LOCK = '''
version = 1
[[package]]
name = "requests"
version = "2.31.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "idna" },
]

[[package]]
name = "myproj"
version = "0.1.0"
source = { editable = "." }
'''


def test_parse_full_sample():
    cfg = parse_config(tomlmini.loads(SAMPLE))
    assert cfg.grace_seconds == 3.0 and cfg.fs_grace_seconds == 7.5
    assert cfg.ignore_paths == ["dist/legacy/**", "vendor/**"]
    assert cfg.ignore_processes == ["tailscaled", "ollama"]
    assert cfg.include_processes == ["my-daemon"]
    assert cfg.checks["deps"] is False and cfg.checks["processes"] is True
    assert [r.kind for r in cfg.rules] == ["generated", "artifact"]
    assert cfg.rules[1].sources == ["docs/**/*.md", "mkdocs.yml"]


def test_fallback_parser_matches_tomllib():
    tomllib = pytest.importorskip("tomllib")
    for text in (SAMPLE, LOCK):
        assert tomlmini.loads(text) == tomllib.loads(text)


def test_lock_parsing_with_fallback():
    data = tomlmini.loads(LOCK)
    assert data["package"][0]["name"] == "requests"
    assert data["package"][1]["source"] == {"editable": "."}
    assert data["package"][0]["dependencies"] == [{"name": "idna"}]


def test_load_config_file_and_errors(tmp_path):
    assert load_config(str(tmp_path)).source is None
    mk(tmp_path, ".whystale.toml", SAMPLE)
    assert load_config(str(tmp_path)).grace_seconds == 3.0
    with pytest.raises(ConfigError):
        load_config(str(tmp_path), str(tmp_path / "missing.toml"))
    mk(tmp_path, "bad.toml", "this is = = not toml [")
    with pytest.raises(ConfigError):
        load_config(str(tmp_path), str(tmp_path / "bad.toml"))


@pytest.mark.parametrize("data", [
    {"checks": {"nonsense": True}},
    {"settings": {"grace_seconds": -1}},
    {"generated": [{"sources": ["a"]}]},
    {"ignore": {"paths": 5}},
])
def test_invalid_config_rejected(data):
    with pytest.raises(ConfigError):
        parse_config(data)
